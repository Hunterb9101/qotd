"""Noon question generation and send workflow."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime

from qotd.domain.contacts import normalize_email_addresses
from qotd.domain.generator import generate_placeholder_question
from qotd.domain.models import StoredQuestion
from qotd.domain.validation import validate_question
from qotd.external.contacts.google import fetch_contact_group_email_addresses
from qotd.external.email.gmail import send_gmail_message
from qotd.external.storage.core import StorageClient
from qotd.presentation.emails import build_participant_email


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


def send_question(config: SendQuestionConfig) -> SendQuestionResult:
    """Generate, send, and persist a QOTD question."""

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
