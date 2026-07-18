"""Noon question generation and send workflow."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Callable

from qotd.domain.dates import question_subject
from qotd.domain.generator import generate_placeholder_question
from qotd.domain.models import Question, StoredQuestion
from qotd.domain.validation import validate_question
from qotd.external.email.core import ParsedEmailMessage
from qotd.external.email.gmail import search_messages, send_gmail_message
from qotd.external.storage.core import StorageClient
from qotd.presentation.emails import build_participant_email
from qotd.usecases.question_history import find_latest_answered_question_before
from qotd.usecases.score_history import ParticipantResults, load_participant_results


MessageFetcher = Callable[[str], list[ParsedEmailMessage]]
QuestionGeneratorForDate = Callable[[date, StorageClient], Question]
LOGGER = logging.getLogger(__name__)
QUESTION_ALREADY_EXISTS = "question_subject_already_exists"


@dataclass(frozen=True)
class SendQuestionConfig:
    """Runtime config for the phase 1 send workflow."""

    game_date: date
    sender: str
    gmail_user: str
    oauth_client_id: str
    oauth_client_secret: str
    oauth_refresh_token: str
    state_store: StorageClient
    google_group_email: str = ""
    question_generator: QuestionGeneratorForDate | None = None
    dry_run: bool = False


@dataclass(frozen=True)
class SendQuestionResult:
    """Result of the phase 1 send workflow."""

    record: StoredQuestion
    email_body: str
    recipient_count: int
    skipped_generated_send: bool = False
    outcome: str = "sent"
    reason: str | None = None
    subject: str | None = None
    matched_gmail_message_id: str | None = None


def organizer_sent_query(*, sender: str, game_date: date) -> str:
    """Build a Gmail query for the exact dated participant question."""

    return f'in:sent from:{sender} subject:"{question_subject(game_date)}"'


def detect_organizer_sent_question(
    messages: list[ParsedEmailMessage],
    *,
    sender: str,
    game_date: date,
) -> ParsedEmailMessage | None:
    """Return the first message whose subject exactly identifies the game date."""

    sender_email = sender.lower()
    expected_subject = question_subject(game_date)
    for message in messages:
        if message.sender_email.lower() != sender_email:
            continue
        if message.subject != expected_subject:
            continue
        if message.message_id.startswith("dry-run:"):
            continue
        return message
    return None


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
        cody_message = detect_organizer_sent_question(
            fetch_messages(organizer_sent_query(sender=config.sender, game_date=config.game_date)),
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
            already_stored = any(
                existing.get("game_date") == record.game_date
                for existing in config.state_store.read_question_records()
            )
            if not already_stored:
                config.state_store.append_question_record(record)
            subject = question_subject(config.game_date)
            LOGGER.info(
                "job=send_question game_date=%s outcome=skipped "
                "reason=%s subject=%r gmail_message_id=%s",
                config.game_date.isoformat(),
                QUESTION_ALREADY_EXISTS,
                subject,
                cody_message.message_id,
            )
            return SendQuestionResult(
                record=record,
                email_body=cody_message.body_text,
                recipient_count=0,
                skipped_generated_send=True,
                outcome="skipped",
                reason=QUESTION_ALREADY_EXISTS,
                subject=subject,
                matched_gmail_message_id=cody_message.message_id,
            )

    google_group_email = config.google_group_email.strip().lower()
    if not config.dry_run and not google_group_email:
        raise RuntimeError("Google Group email is required for participant delivery")

    if config.question_generator is None:
        question = generate_placeholder_question(config.game_date.isoformat())
    else:
        question = config.question_generator(config.game_date, config.state_store)
    validate_question(question)
    previous_question = find_latest_answered_question_before(config.state_store, config.game_date)
    participant_results = ParticipantResults(point_earners=(), standings=())
    if previous_question is not None:
        participant_results = load_participant_results(
            config.state_store,
            date.fromisoformat(previous_question.game_date),
        )
    email_message = build_participant_email(
        question,
        config.sender,
        delivery_address=google_group_email or None,
        point_earners=participant_results.point_earners,
        previous_question=previous_question,
        standings=participant_results.standings,
    )

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
        recipient_count=1,
        subject=question_subject(config.game_date),
    )
