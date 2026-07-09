"""Noon question generation and send workflow."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from qotd.emailing import build_participant_email, send_gmail_message
from qotd.generator import generate_placeholder_question
from qotd.models import StoredQuestion
from qotd.storage import append_question_record
from qotd.validation import validate_question


@dataclass(frozen=True)
class SendQuestionConfig:
    """Runtime config for the phase 1 send workflow."""

    game_date: date
    sender: str
    mailing_list: str
    state_path: Path
    delegated_user: str
    service_account_file: str
    dry_run: bool = False


@dataclass(frozen=True)
class SendQuestionResult:
    """Result of the phase 1 send workflow."""

    record: StoredQuestion
    email_body: str


def send_question(config: SendQuestionConfig) -> SendQuestionResult:
    """Generate, send, and persist a QOTD question."""

    question = generate_placeholder_question(config.game_date.isoformat())
    validate_question(question)
    email_message = build_participant_email(question, config.sender, config.mailing_list)

    if config.dry_run:
        gmail_message_id = f"dry-run:{config.game_date.isoformat()}"
    else:
        gmail_message_id = send_gmail_message(
            email_message,
            delegated_user=config.delegated_user,
            service_account_file=config.service_account_file,
        )

    record = StoredQuestion.from_question(
        question=question,
        gmail_message_id=gmail_message_id,
        created_at=datetime.now(UTC),
    )
    append_question_record(config.state_path, record)
    return SendQuestionResult(record=record, email_body=email_message.get_content())

