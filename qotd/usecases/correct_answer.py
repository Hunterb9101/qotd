"""Manual correct-answer update workflow."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from email.message import EmailMessage
from typing import Callable
from urllib.parse import urlparse

from qotd.domain.contacts import normalize_email_addresses
from qotd.domain.models import CorrectAnswerUpdate, OPTION_LABELS
from qotd.external.email.core import ParsedEmailMessage
from qotd.external.email.gmail import mark_gmail_message_read, search_messages, send_gmail_message
from qotd.external.storage.core import StorageClient
from qotd.presentation.emails import build_organizer_email


@dataclass(frozen=True)
class ParsedCorrectAnswerRequest:
    """Structured correct-answer update parsed from an organizer email."""

    game_date: date
    correct_option: str
    source_url: str
    idempotency_key: str | None = None


@dataclass(frozen=True)
class CorrectAnswerResult:
    """Result of applying one correct-answer update."""

    update: CorrectAnswerUpdate
    applied: bool


@dataclass(frozen=True)
class ProcessCorrectAnswerEmailsConfig:
    """Configuration for processing correct-answer emails."""

    sender: str
    gmail_user: str
    organizer_emails: tuple[str, ...]
    oauth_client_id: str
    oauth_client_secret: str
    oauth_refresh_token: str
    state_store: StorageClient
    query: str = 'is:unread "Action: set-correct-answer"'
    max_results: int = 25
    dry_run: bool = False


@dataclass(frozen=True)
class CorrectAnswerEmailProcessingResult:
    """Result for one correct-answer request email."""

    message_id: str
    sender_email: str
    accepted: bool
    response_message_id: str
    status: str
    update_result: CorrectAnswerResult | None = None


@dataclass(frozen=True)
class ProcessCorrectAnswerEmailsResult:
    """Summary of a correct-answer processing run."""

    searched_query: str
    processed: tuple[CorrectAnswerEmailProcessingResult, ...]


def parse_correct_answer_email(body_text: str) -> ParsedCorrectAnswerRequest:
    """Parse a plain-text correct-answer update email."""

    fields: dict[str, str] = {}
    for raw_line in body_text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if ":" not in raw_line:
            continue
        key, value = raw_line.split(":", 1)
        fields[key.strip().lower()] = value.strip()

    if fields.get("action", "").casefold() != "set-correct-answer":
        raise ValueError("Action must be set-correct-answer")
    if not fields.get("game date"):
        raise ValueError("Game date is required")
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

    return ParsedCorrectAnswerRequest(
        game_date=date.fromisoformat(fields["game date"]),
        correct_option=correct_option,
        source_url=fields["source url"],
        idempotency_key=fields.get("idempotency key") or None,
    )


def apply_correct_answer_update(
    *,
    request: ParsedCorrectAnswerRequest,
    source_gmail_message_id: str,
    state_store: StorageClient,
    dry_run: bool = False,
) -> CorrectAnswerResult:
    """Append one correct-answer update if it has not already been applied."""

    game_date_text = request.game_date.isoformat()
    if not any(record.get("game_date") == game_date_text for record in state_store.read_question_records()):
        raise ValueError(f"no stored question exists for {game_date_text}")

    idempotency_key = request.idempotency_key or f"correct-answer:{game_date_text}:{request.correct_option}"
    update = CorrectAnswerUpdate(
        game_date=game_date_text,
        correct_option=request.correct_option,
        source_url=request.source_url,
        source_gmail_message_id=source_gmail_message_id,
        idempotency_key=idempotency_key,
        created_at=datetime.now(UTC).isoformat(),
    )
    if any(record.get("idempotency_key") == idempotency_key for record in state_store.read_correct_answer_updates()):
        return CorrectAnswerResult(update=update, applied=False)
    if not dry_run:
        state_store.append_correct_answer_update(update)
    return CorrectAnswerResult(update=update, applied=True)


def correct_answer_response_body(
    *,
    request_message: ParsedEmailMessage,
    result: CorrectAnswerResult | None,
    error: str | None = None,
) -> str:
    """Build a correct-answer confirmation or rejection body."""

    if error is not None:
        return (
            "Correct answer request rejected.\n\n"
            f"Message: {request_message.message_id}\n"
            f"Reason: {error}\n\n"
            "Expected template:\n"
            "Action: set-correct-answer\n"
            "Game date: 2026-07-08\n"
            "Correct option: C\n"
            "Source URL: https://example.com/source-for-answer\n"
        )
    if result is None:
        raise ValueError("result is required when error is not provided")
    status = "Skipped duplicate" if not result.applied else "Applied"
    return (
        f"{status} correct answer update.\n\n"
        f"Game date: {result.update.game_date}\n"
        f"Correct option: {result.update.correct_option}\n"
        f"Source URL: {result.update.source_url}\n"
        f"Idempotency key: {result.update.idempotency_key}\n"
    )


def process_correct_answer_emails(
    config: ProcessCorrectAnswerEmailsConfig,
    *,
    fetch_messages: Callable[[str], list[ParsedEmailMessage]] | None = None,
    send_message: Callable[[EmailMessage], str] | None = None,
    mark_message_handled: Callable[[str], None] | None = None,
) -> ProcessCorrectAnswerEmailsResult:
    """Process correct-answer request emails from approved organizers."""

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

    processed: list[CorrectAnswerEmailProcessingResult] = []
    for message in fetch(config.query):
        normalized_sender = normalize_email_addresses([message.sender_email])
        sender_email = normalized_sender[0] if normalized_sender else message.sender_email
        update_result: CorrectAnswerResult | None = None
        error: str | None = None
        if sender_email not in approved_senders:
            error = f"sender is not approved: {sender_email}"
        else:
            try:
                request = parse_correct_answer_email(message.body_text)
                update_result = apply_correct_answer_update(
                    request=request,
                    source_gmail_message_id=message.message_id,
                    state_store=config.state_store,
                    dry_run=config.dry_run,
                )
            except ValueError as exc:
                error = str(exc)

        response = build_organizer_email(
            sender=config.sender,
            organizer=sender_email,
            subject="QOTD correct answer update result",
            body=correct_answer_response_body(request_message=message, result=update_result, error=error),
        )
        response_message_id = f"dry-run:{message.message_id}"
        if not config.dry_run:
            response_message_id = send(response)
            mark_handled(message.message_id)
        processed.append(
            CorrectAnswerEmailProcessingResult(
                message_id=message.message_id,
                sender_email=sender_email,
                accepted=error is None,
                response_message_id=response_message_id,
                status=error or ("skipped_duplicate" if update_result and not update_result.applied else "applied"),
                update_result=update_result,
            )
        )

    return ProcessCorrectAnswerEmailsResult(searched_query=config.query, processed=tuple(processed))
