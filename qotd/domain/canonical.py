"""Canonical QOTD state records and lifecycle constants."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from hashlib import sha256
from uuid import uuid4


GAME_PENDING = "pending"
GAME_PUBLISHED = "published"
GAME_SCORED = "scored"
GAME_STATUSES = (GAME_PENDING, GAME_PUBLISHED, GAME_SCORED)

PUBLICATION_AUTOMATED = "automated"
PUBLICATION_MANUAL = "manual"

INSTRUCTION_APPLIED = "applied"
INSTRUCTION_DUPLICATE = "duplicate"
INSTRUCTION_REJECTED = "rejected"

SCORE_EVENT_AUTOMATIC = "automatic"
SCORE_EVENT_MANUAL = "manual"

OUTBOUND_PENDING = "pending"
OUTBOUND_SENT = "sent"


def new_id() -> str:
    """Return an application-generated UUID string."""

    return str(uuid4())


def gmail_message_key(message_id: str) -> str:
    """Return the one-way idempotency key for a Gmail message identity."""

    return sha256(message_id.encode()).hexdigest()


@dataclass(frozen=True)
class Series:
    id: str
    name: str
    starts_on: date
    ends_on: date
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class Player:
    id: str
    email: str
    nickname: str | None = None


@dataclass(frozen=True)
class Game:
    id: str
    series_id: str
    day: date
    status: str
    publication_mode: str
    deadline_at: datetime
    created_at: datetime
    updated_at: datetime
    question_prompt: str | None = None
    question_options: dict[str, str] | None = None
    publication_subject: str | None = None
    published_at: datetime | None = None
    publication_message_key: str | None = None
    publication_instruction_id: str | None = None
    correct_option: str | None = None
    answer_source_url: str | None = None
    answer_source_note: str | None = None
    answer_instruction_id: str | None = None
    scored_at: datetime | None = None


@dataclass(frozen=True)
class OrganizerInstruction:
    id: str
    source_message_key: str
    sender_email: str
    subject: str
    received_at: datetime
    action: str
    status: str
    processed_at: datetime
    rejection_reason: str | None = None


@dataclass(frozen=True)
class Submission:
    id: str
    source_message_key: str
    game_id: str
    player_id: str
    body_text: str
    received_at: datetime
    is_eligible: bool
    created_at: datetime
    updated_at: datetime
    interpreted_option: str | None = None
    ineligibility_reason: str | None = None


@dataclass(frozen=True)
class ScoreEvent:
    id: str
    idempotency_key: str
    player_id: str
    series_id: str
    event_type: str
    points_delta: int
    created_at: datetime
    game_id: str | None = None
    submission_id: str | None = None
    organizer_instruction_id: str | None = None
    reason: str | None = None


@dataclass(frozen=True)
class OutboundMessage:
    id: str
    idempotency_key: str
    message_type: str
    recipient: str
    subject: str
    body_text: str
    status: str
    created_at: datetime
    game_id: str | None = None
    organizer_instruction_id: str | None = None
    source_message_key: str | None = None
    sent_at: datetime | None = None


@dataclass(frozen=True)
class ScoreboardEntry:
    series_id: str
    player_id: str
    email: str
    score: int
