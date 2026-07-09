"""Noon question generation and send workflow."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Callable

from qotd.domain.contacts import normalize_email_addresses
from qotd.domain.generator import generate_placeholder_question
from qotd.domain.models import StoredQuestion
from qotd.domain.validation import validate_question
from qotd.external.contacts.google import fetch_contact_group_email_addresses
from qotd.external.email.core import ParsedEmailMessage
from qotd.external.email.gmail import search_messages, send_gmail_message
from qotd.external.storage.core import StorageClient
from qotd.presentation.emails import build_participant_email


MessageFetcher = Callable[[str], list[ParsedEmailMessage]]


@dataclass(frozen=True)
class SendQuestionConfig:
    """Runtime config for the phase 1 send workflow."""

    game_date: date
    sender: str
    contact_group_name: str
    gmail_user: str
    oauth_client_id: str
    oauth_client_secret: str
    oauth_refresh_token: str
    state_store: StorageClient
    participant_emails: tuple[str, ...] = ()
    dry_run: bool = False


@dataclass(frozen=True)
class SendQuestionResult:
    """Result of the phase 1 send workflow."""

    record: StoredQuestion
    email_body: str
    recipient_count: int
    skipped_generated_send: bool = False


def cody_sent_query(*, sender: str, game_date: date) -> str:
    """Build a Gmail query for same-day human-authored QOTD messages."""

    after = game_date.strftime("%Y/%m/%d")
    before = (game_date + timedelta(days=1)).strftime("%Y/%m/%d")
    return f'from:{sender} subject:QOTD after:{after} before:{before}'


def detect_cody_sent_question(
    messages: list[ParsedEmailMessage],
    *,
    sender: str,
    game_date: date,
) -> ParsedEmailMessage | None:
    """Return the first same-day non-automated QOTD message from the sender."""

    sender_email = sender.lower()
    for message in messages:
        if message.sender_email.lower() != sender_email:
            continue
        if message.message_id.startswith("dry-run:"):
            continue
        if message.sent_at is not None and message.sent_at.date() != game_date:
            continue
        return message
    return None


def resolve_participant_emails(config: SendQuestionConfig) -> list[str]:
    """Resolve participant email addresses from override values or Google Contacts."""

    if config.participant_emails:
        email_addresses = normalize_email_addresses(config.participant_emails)
    else:
        email_addresses = fetch_contact_group_email_addresses(
            oauth_client_id=config.oauth_client_id,
            oauth_client_secret=config.oauth_client_secret,
            oauth_refresh_token=config.oauth_refresh_token,
            group_name=config.contact_group_name,
        )

    if not email_addresses:
        raise RuntimeError("No QOTD participant email addresses found")
    return email_addresses


def send_question(
    config: SendQuestionConfig,
    *,
    fetch_messages: MessageFetcher | None = None,
) -> SendQuestionResult:
    """Generate, send, and persist a QOTD question."""

    if fetch_messages is None and not config.dry_run:
        def fetch_messages(gmail_query: str) -> list[ParsedEmailMessage]:
            return search_messages(
                user_id=config.gmail_user,
                oauth_client_id=config.oauth_client_id,
                oauth_client_secret=config.oauth_client_secret,
                oauth_refresh_token=config.oauth_refresh_token,
                query=gmail_query,
            )

    if fetch_messages is not None:
        cody_message = detect_cody_sent_question(
            fetch_messages(cody_sent_query(sender=config.sender, game_date=config.game_date)),
            sender=config.sender,
            game_date=config.game_date,
        )
        if cody_message is not None:
            record = StoredQuestion(
                game_date=config.game_date.isoformat(),
                prompt=cody_message.body_text,
                options={},
                correct_option="",
                source_note="Manual QOTD sent by Cody; correct answer pending.",
                source_url="",
                source="manual",
                gmail_message_id=cody_message.message_id,
                created_at=(cody_message.sent_at or datetime.now(UTC)).isoformat(),
            )
            config.state_store.append_question_record(record)
            return SendQuestionResult(
                record=record,
                email_body=cody_message.body_text,
                recipient_count=0,
                skipped_generated_send=True,
            )

    question = generate_placeholder_question(config.game_date.isoformat())
    validate_question(question)
    participant_emails = resolve_participant_emails(config)
    email_message = build_participant_email(question, config.sender, participant_emails)

    if config.dry_run:
        gmail_message_id = f"dry-run:{config.game_date.isoformat()}"
    else:
        gmail_message_id = send_gmail_message(
            email_message,
            user_id=config.gmail_user,
            oauth_client_id=config.oauth_client_id,
            oauth_client_secret=config.oauth_client_secret,
            oauth_refresh_token=config.oauth_refresh_token,
        )

    record = StoredQuestion.from_question(
        question=question,
        gmail_message_id=gmail_message_id,
        created_at=datetime.now(UTC),
    )
    config.state_store.append_question_record(record)
    return SendQuestionResult(
        record=record,
        email_body=email_message.get_content(),
        recipient_count=len(participant_emails),
    )
