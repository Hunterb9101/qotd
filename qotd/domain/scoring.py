"""Reply interpretation and scoring for QOTD."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime

from qotd.domain.canonical import gmail_message_key
from qotd.domain.models import ScoreboardLine, SubmissionCandidate


ANSWER_RE = re.compile(r"^[A-D]$", re.IGNORECASE)


@dataclass(frozen=True)
class AnswerInterpretation:
    """Interpreted answer for one reply."""

    option: str
    needs_review: bool


@dataclass(frozen=True)
class ScoredReply:
    """Scoring result for one Player Submission."""

    email: str
    gmail_message_id: str
    interpreted_option: str
    points_awarded: int
    needs_review: bool


@dataclass(frozen=True)
class ScoringResult:
    """Result of scoring one QOTD game day."""

    game_date: str
    correct: tuple[ScoredReply, ...]
    incorrect: tuple[ScoredReply, ...]
    needs_review: tuple[ScoredReply, ...]
    skipped_processing_keys: tuple[str, ...]
    standings: tuple[ScoreboardLine, ...]
    no_response: tuple[str, ...] = ()
    ineligible_senders: tuple[str, ...] = ()


def parse_deterministic_answer(body_text: str) -> AnswerInterpretation:
    """Interpret a simple A/B/C/D reply without AI."""

    candidate = body_text.strip()
    if ANSWER_RE.fullmatch(candidate):
        return AnswerInterpretation(option=candidate.upper(), needs_review=False)
    return AnswerInterpretation(option="UNKNOWN", needs_review=True)


def parse_iso_datetime(value: str) -> datetime:
    """Parse an ISO datetime, treating naive values as UTC."""

    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def select_latest_eligible_replies(
    replies: list[SubmissionCandidate],
    *,
    cutoff_at: datetime,
) -> dict[str, SubmissionCandidate]:
    """Select the latest reply per sender before the cutoff."""

    selected: dict[str, SubmissionCandidate] = {}
    for reply in replies:
        if not reply.received_at:
            continue
        received_at = parse_iso_datetime(reply.received_at)
        if received_at >= cutoff_at:
            continue
        current = selected.get(reply.sender_email)
        if current is None or (received_at, gmail_message_key(reply.gmail_message_id)) > (
            parse_iso_datetime(current.received_at), gmail_message_key(current.gmail_message_id)
        ):
            selected[reply.sender_email] = reply
    return selected

