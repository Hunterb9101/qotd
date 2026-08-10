"""Organizer Answer-instruction workflow."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from email.message import EmailMessage
from typing import Callable
from urllib.parse import urlparse

from qotd.domain.contacts import normalize_email_addresses
from qotd.domain.canonical import OUTBOUND_PENDING, OutboundMessage, new_id
from qotd.domain.models import OPTION_LABELS
from qotd.external.email.core import ParsedEmailMessage
from qotd.external.email.runtime import build_organizer_email, mark_gmail_message_read, search_messages, send_gmail_message
from qotd.external.storage.canonical import CanonicalState
from qotd.usecases.handle_answer import apply_answer_instruction
from qotd.usecases.parse_organizer_instruction import parse_organizer_instruction_payload
from qotd.usecases.deliver_outbound_message import deliver_outbound_message


ANSWER_INSTRUCTION_QUERY = 'is:unread {"Action: set-answer" "Action: set-answer"}'


@dataclass(frozen=True)
class ParsedSetAnswerRequest:
    """Structured Answer instruction parsed from an Organizer email."""

    day: date
    correct_option: str
    source_url: str
    idempotency_key: str | None = None


@dataclass(frozen=True)
class SetAnswerResult:
    """Result of applying one Answer instruction."""

    update: ParsedSetAnswerRequest
    applied: bool


@dataclass(frozen=True)
class ProcessSetAnswerEmailsConfig:
    """Configuration for processing Organizer Answer emails."""

    sender: str
    gmail_user: str
    organizer_emails: tuple[str, ...]
    oauth_client_id: str
    oauth_client_secret: str
    oauth_refresh_token: str
    state_store: object
    query: str = ANSWER_INSTRUCTION_QUERY
    max_results: int = 25
    dry_run: bool = False


@dataclass(frozen=True)
class SetAnswerEmailProcessingResult:
    """Result for one Organizer Answer request email."""

    message_id: str
    sender_email: str
    accepted: bool
    response_message_id: str
    status: str
    update_result: SetAnswerResult | None = None


@dataclass(frozen=True)
class ProcessSetAnswerEmailsResult:
    """Summary of an Answer-instruction processing run."""

    searched_query: str
    processed: tuple[SetAnswerEmailProcessingResult, ...]


def parse_set_answer_email(body_text: str) -> ParsedSetAnswerRequest:
    """Parse a plain-text Answer instruction email."""

    payload = parse_organizer_instruction_payload(body_text)
    fields = payload.fields
    if payload.action != "set-answer":
        raise ValueError("Action must be set-answer")
    if not fields.get("day"):
        raise ValueError("Day is required")
    if not fields.get("correct option"):
        raise ValueError("Correct option is required")
    if not fields.get("source url"):
        raise ValueError("Source URL is required")

    correct_option = fields["correct option"].upper()
    if correct_option not in OPTION_LABELS:
        raise ValueError("Correct option must be one of A, B, C, or D")
    parsed_url = urlparse(fields["source url"])
    if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
        raise ValueError("Source URL must be a valid http or https URL")

    return ParsedSetAnswerRequest(
        day=date.fromisoformat(fields["day"]),
        correct_option=correct_option,
        source_url=fields["source url"],
        idempotency_key=fields.get("idempotency key") or None,
    )


def set_answer_response_body(
    *,
    request_message: ParsedEmailMessage,
    result: SetAnswerResult | None,
    error: str | None = None,
) -> str:
    """Build an Answer confirmation or rejection body."""

    if error is not None:
        return (
            "Answer instruction rejected.\n\n"
            f"Message: {request_message.message_id}\n"
            f"Reason: {error}\n\n"
            "Expected template:\n"
            "Action: set-answer\n"
            "Day: 2026-07-08\n"
            "Correct option: C\n"
            "Source URL: https://example.com/source-for-answer\n"
        )
    if result is None:
        raise ValueError("result is required when error is not provided")
    status = "Skipped duplicate" if not result.applied else "Applied"
    return (
        f"{status} Answer instruction.\n\n"
        f"Day: {result.update.day.isoformat()}\n"
        f"Correct option: {result.update.correct_option}\n"
        f"Source URL: {result.update.source_url}\n"
        f"Idempotency key: {result.update.idempotency_key or 'Gmail message identity'}\n"
    )


def process_set_answer_emails(
    config: ProcessSetAnswerEmailsConfig,
    *,
    fetch_messages: Callable[[str], list[ParsedEmailMessage]] | None = None,
    send_message: Callable[[EmailMessage], str] | None = None,
    mark_message_handled: Callable[[str], None] | None = None,
) -> ProcessSetAnswerEmailsResult:
    """Process Organizer Answer instructions from approved Organizers."""

    if not isinstance(config.state_store, CanonicalState):
        raise TypeError("canonical Game state is required")
    state = config.state_store
    approved_senders = set(normalize_email_addresses(config.organizer_emails))
    if not approved_senders:
        raise ValueError("at least one organizer email is required")

    fetch = fetch_messages or (
        lambda query: search_messages(
            user_id=config.gmail_user,
            oauth_client_id=config.oauth_client_id,
            oauth_client_secret=config.oauth_client_secret,
            oauth_refresh_token=config.oauth_refresh_token,
            query=query,
            max_results=config.max_results,
        )
    )
    send = send_message or (
        lambda message: send_gmail_message(
            message,
            user_id=config.gmail_user,
            oauth_client_id=config.oauth_client_id,
            oauth_client_secret=config.oauth_client_secret,
            oauth_refresh_token=config.oauth_refresh_token,
        )
    )
    mark_handled = mark_message_handled or (
        lambda message_id: mark_gmail_message_read(
            message_id,
            user_id=config.gmail_user,
            oauth_client_id=config.oauth_client_id,
            oauth_client_secret=config.oauth_client_secret,
            oauth_refresh_token=config.oauth_refresh_token,
        )
    )

    processed: list[SetAnswerEmailProcessingResult] = []
    for message in fetch(config.query):
        normalized_sender = normalize_email_addresses([message.sender_email])
        sender_email = normalized_sender[0] if normalized_sender else message.sender_email
        update_result: SetAnswerResult | None = None
        instruction_id: str | None = None
        error: str | None = None
        if sender_email not in approved_senders:
            error = f"sender is not approved: {sender_email}"
        else:
            try:
                canonical_result = apply_answer_instruction(
                    state=state,
                    message=message,
                    processed_at=datetime.now(UTC),
                )
                instruction_id = canonical_result.instruction.id
                if canonical_result.instruction.status == "rejected":
                    error = canonical_result.instruction.rejection_reason or "Organizer Instruction rejected"
                else:
                    request = parse_set_answer_email(message.body_text)
                    update_result = SetAnswerResult(
                        update=request,
                        applied=canonical_result.instruction.status == "applied",
                    )
            except ValueError as exc:
                error = str(exc)

        response_body = set_answer_response_body(request_message=message, result=update_result, error=error)
        response = build_organizer_email(
            sender=config.sender,
            organizer=sender_email,
            subject="QOTD Answer instruction result",
            body=response_body,
        )
        response_message_id = f"dry-run:{message.message_id}"
        if not config.dry_run:
            outcome_key = f"answer-outcome:{message.message_id}"
            existing_intent = state.find_outbound_message(idempotency_key=outcome_key)
            intent = existing_intent or state.record_outbound_message(
                OutboundMessage(
                    id=new_id(), idempotency_key=outcome_key, message_type="organizer_instruction_outcome",
                    recipient=sender_email, subject=str(response["Subject"]), body_text=response_body,
                    status=OUTBOUND_PENDING, created_at=datetime.now(UTC), organizer_instruction_id=instruction_id,
                )
            )
            response_message_id = deliver_outbound_message(
                state=state, intent=intent, sender=config.sender, fetch_messages=fetch, send_message=send,
                is_new=existing_intent is None,
            )
            mark_handled(message.message_id)
        processed.append(
            SetAnswerEmailProcessingResult(
                message_id=message.message_id,
                sender_email=sender_email,
                accepted=error is None,
                response_message_id=response_message_id,
                status=error or ("skipped_duplicate" if update_result and not update_result.applied else "applied"),
                update_result=update_result,
            )
        )

    return ProcessSetAnswerEmailsResult(searched_query=config.query, processed=tuple(processed))
