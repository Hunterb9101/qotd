"""Check for and capture an organizer-sent QOTD question."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Callable

from qotd.domain.dates import question_subject
from qotd.domain.models import StoredQuestion
from qotd.external.email.core import ParsedEmailMessage
from qotd.external.storage.core import StorageClient


MessageFetcher = Callable[[str], list[ParsedEmailMessage]]


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


def check_manual_question(
    *,
    game_date: date,
    sender: str,
    state_store: StorageClient,
    fetch_messages: MessageFetcher,
) -> StoredQuestion | None:
    """Persist and return the organizer's question when one was already sent."""

    message = detect_organizer_sent_question(
        fetch_messages(organizer_sent_query(sender=sender, game_date=game_date)),
        sender=sender,
        game_date=game_date,
    )
    if message is None:
        return None
    record = StoredQuestion(
        game_date=game_date.isoformat(),
        prompt=message.body_text,
        options={},
        correct_option="",
        source_note="Manual QOTD sent by Cody; correct answer pending.",
        source_url="",
        source="manual",
        gmail_message_id=message.message_id,
        created_at=(message.sent_at or datetime.now(UTC)).isoformat(),
    )
    already_stored = any(
        existing.get("game_date") == record.game_date
        for existing in state_store.read_question_records()
    )
    if not already_stored:
        state_store.append_question_record(record)
    return record
