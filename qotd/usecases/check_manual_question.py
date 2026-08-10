"""Check for and capture an organizer-sent QOTD question."""

from __future__ import annotations

from datetime import UTC, date, datetime
import re
from typing import Callable

from qotd.domain.dates import question_subject
from qotd.domain.canonical import GAME_PENDING, OUTBOUND_SENT, Game, OutboundMessage, gmail_message_key, new_id
from qotd.domain.models import Question, StoredQuestion
from qotd.external.email.core import ParsedEmailMessage
from qotd.external.storage.canonical import CanonicalState
from qotd.usecases.publish_game import publish_manual_game


MessageFetcher = Callable[[str], list[ParsedEmailMessage]]
OPTION_LINE = re.compile(r"^([A-D])[).:]\s+(.+)$")


def organizer_sent_query(*, sender: str, game_date: date) -> str:
    """Build a Gmail query for the exact dated Player Question."""

    return f'in:sent from:{sender} subject:"{question_subject(game_date)}"'


def detect_organizer_sent_question(
    messages: list[ParsedEmailMessage],
    *,
    sender: str,
    game_date: date,
) -> ParsedEmailMessage | None:
    """Return the first message whose subject exactly identifies the Game Day."""

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
    state: CanonicalState,
    fetch_messages: MessageFetcher,
) -> Game | StoredQuestion | None:
    """Persist and return the organizer's question when one was already sent."""

    message = detect_organizer_sent_question(
        fetch_messages(organizer_sent_query(sender=sender, game_date=game_date)),
        sender=sender,
        game_date=game_date,
    )
    if message is None:
        return None
    existing = state.find_game(day=game_date)
    if existing is not None and existing.status != GAME_PENDING:
        return existing
    published_at = message.sent_at or datetime.now(UTC)
    question = manual_question_from_message(message, game_date=game_date)
    if question is None:
        return None
    message_key = gmail_message_key(message.message_id)
    outbound = OutboundMessage(
        id=new_id(), idempotency_key=f"manual-publication:{message_key}", message_type="question_publication",
        recipient="", subject=message.subject, body_text=message.body_text, status=OUTBOUND_SENT,
        created_at=published_at, game_id=existing.id if existing is not None else new_id(),
        source_message_key=message_key, sent_at=published_at,
    )
    return publish_manual_game(
        state=state,
        game_day=game_date,
        question=question,
        message_id=message_key,
        published_at=published_at,
        outbound_message=outbound,
        game_id=existing.id if existing is not None else outbound.game_id,
    )


def manual_question_from_message(message: ParsedEmailMessage, *, game_date: date) -> Question | None:
    """Capture a valid four-option manual Question from its published body."""

    prompt_lines: list[str] = []
    options: dict[str, str] = {}
    for raw_line in message.body_text.splitlines():
        match = OPTION_LINE.match(raw_line.strip())
        if match:
            options[match.group(1)] = match.group(2).strip()
        else:
            prompt_lines.append(raw_line)
    if set(options) != {"A", "B", "C", "D"}:
        return None
    prompt = "\n".join(prompt_lines).strip()
    if not prompt:
        return None
    return Question(
        game_date=game_date.isoformat(), prompt=prompt, options=options, correct_option="",
        source_note="Manual Question; Answer pending.", source_url="", source="manual",
    )
