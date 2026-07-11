"""Reply interpretation and scoring for QOTD."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Callable

from qotd.domain.dates import monthly_series
from qotd.domain.models import MonthlyScore, ReplyCandidate, ReplyProcessingRecord, StoredQuestion


ANSWER_RE = re.compile(r"^[A-D]$", re.IGNORECASE)


@dataclass(frozen=True)
class AnswerInterpretation:
    """Interpreted answer for one reply."""

    option: str
    needs_review: bool


@dataclass(frozen=True)
class ScoredReply:
    """Scoring result for one participant reply."""

    email: str
    gmail_message_id: str
    interpreted_option: str
    points_awarded: int
    needs_review: bool


@dataclass(frozen=True)
class ReplyProcessingUpdate:
    """Reply-processing record plus derived interpretation metadata."""

    record: ReplyProcessingRecord
    interpreted_option: str | None


@dataclass(frozen=True)
class ScoringResult:
    """Result of scoring one QOTD game day."""

    game_date: str
    correct: tuple[ScoredReply, ...]
    incorrect: tuple[ScoredReply, ...]
    needs_review: tuple[ScoredReply, ...]
    skipped_processing_keys: tuple[str, ...]
    standings: tuple[MonthlyScore, ...]
    no_response: tuple[str, ...] = ()
    ineligible_senders: tuple[str, ...] = ()
    monthly_score_updates: tuple[MonthlyScore, ...] = ()
    reply_processing_updates: tuple[ReplyProcessingUpdate, ...] = ()


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
    replies: list[ReplyCandidate],
    *,
    cutoff_at: datetime,
) -> dict[str, ReplyCandidate]:
    """Select the latest reply per sender before the cutoff."""

    selected: dict[str, ReplyCandidate] = {}
    for reply in replies:
        if not reply.received_at:
            continue
        received_at = parse_iso_datetime(reply.received_at)
        if received_at >= cutoff_at:
            continue
        current = selected.get(reply.sender_email)
        if current is None or received_at > parse_iso_datetime(current.received_at):
            selected[reply.sender_email] = reply
    return selected


def processed_keys(records: list[dict[str, Any]]) -> set[str]:
    """Return processed reply keys from stored processing records."""

    keys: set[str] = set()
    for record in records:
        key = record.get("processing_key")
        if isinstance(key, str) and key:
            keys.add(key)
            continue
        game_date = record.get("game_date")
        email = record.get("email")
        if isinstance(game_date, str) and isinstance(email, str):
            keys.add(f"{game_date}:{email}")
    return keys


def latest_score_map(records: list[dict[str, Any]], *, series: str) -> dict[str, int]:
    """Return latest score totals by email for one monthly series."""

    scores: dict[str, int] = {}
    for record in records:
        if record.get("series") != series:
            continue
        email = record.get("email")
        points = record.get("points")
        if isinstance(email, str) and isinstance(points, int):
            scores[email] = points
    return scores


def standings_from_scores(series: str, scores: dict[str, int]) -> tuple[MonthlyScore, ...]:
    """Build sorted standings records from score totals."""

    return tuple(
        MonthlyScore(series=series, email=email, points=points)
        for email, points in sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    )


def score_replies(
    *,
    question: StoredQuestion,
    replies: list[ReplyCandidate],
    cutoff_at: datetime,
    processed_at: datetime,
    existing_reply_processing_records: list[dict[str, Any]] | None = None,
    existing_monthly_score_records: list[dict[str, Any]] | None = None,
    interpret_answer: Callable[[str], AnswerInterpretation] = parse_deterministic_answer,
    eligible_emails: list[str] | tuple[str, ...] | None = None,
) -> ScoringResult:
    """Score latest eligible replies and return persistence updates."""

    eligible = None if eligible_emails is None else {email.strip().lower() for email in eligible_emails}
    ineligible_senders = sorted(
        {
            reply.sender_email.strip().lower()
            for reply in replies
            if eligible is not None and reply.sender_email.strip().lower() not in eligible
        }
    )
    eligible_replies = replies if eligible is None else [
        reply for reply in replies if reply.sender_email.strip().lower() in eligible
    ]
    selected_replies = select_latest_eligible_replies(eligible_replies, cutoff_at=cutoff_at)
    existing_keys = processed_keys(existing_reply_processing_records or [])
    game_date = parse_iso_datetime(f"{question.game_date}T00:00:00+00:00").date()
    series = monthly_series(game_date)
    scores = latest_score_map(existing_monthly_score_records or [], series=series)
    if eligible is not None:
        scores = {email: scores.get(email, 0) for email in eligible}

    correct: list[ScoredReply] = []
    incorrect: list[ScoredReply] = []
    needs_review: list[ScoredReply] = []
    skipped_keys: list[str] = []
    monthly_score_updates: list[MonthlyScore] = []
    reply_processing_updates: list[ReplyProcessingUpdate] = []

    for email, reply in sorted(selected_replies.items()):
        processing_key = reply.processing_key
        if processing_key in existing_keys:
            skipped_keys.append(processing_key)
            continue

        interpretation = interpret_answer(reply.body_text)
        points_awarded = int(
            not interpretation.needs_review
            and interpretation.option == question.correct_option
        )
        scored_reply = ScoredReply(
            email=email,
            gmail_message_id=reply.gmail_message_id,
            interpreted_option=interpretation.option,
            points_awarded=points_awarded,
            needs_review=interpretation.needs_review,
        )
        if interpretation.needs_review:
            needs_review.append(scored_reply)
        elif points_awarded:
            correct.append(scored_reply)
        else:
            incorrect.append(scored_reply)

        scores[email] = scores.get(email, 0) + points_awarded
        monthly_score_updates.append(MonthlyScore(series=series, email=email, points=scores[email]))
        reply_processing_updates.append(
            ReplyProcessingUpdate(
                record=ReplyProcessingRecord(
                    game_date=question.game_date,
                    email=email,
                    latest_gmail_message_id=reply.gmail_message_id,
                    points_awarded=points_awarded,
                    needs_audit=interpretation.needs_review,
                    processed_at=processed_at.isoformat(),
                ),
                interpreted_option=interpretation.option,
            )
        )

    return ScoringResult(
        game_date=question.game_date,
        correct=tuple(correct),
        incorrect=tuple(incorrect),
        needs_review=tuple(needs_review),
        skipped_processing_keys=tuple(skipped_keys),
        standings=standings_from_scores(series, scores),
        no_response=tuple(sorted((eligible or set()) - set(selected_replies))),
        ineligible_senders=tuple(ineligible_senders),
        monthly_score_updates=tuple(monthly_score_updates),
        reply_processing_updates=tuple(reply_processing_updates),
    )
