"""Core data contracts for QOTD workflows."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any


OPTION_LABELS = ("A", "B", "C", "D")


@dataclass(frozen=True)
class QuestionTopic:
    """Topic direction used to generate a question."""

    title: str
    summary: str
    source_url: str
    lenses: tuple[str, ...] = ()


@dataclass(frozen=True)
class Question:
    """Structured generated question data."""

    game_date: str
    prompt: str
    options: dict[str, str]
    correct_option: str
    source_note: str
    source_url: str
    source: str = "generated"


@dataclass(frozen=True)
class GeneratedQuestionCandidate:
    """Generated question and the metadata needed to audit it."""

    question: Question
    topic_source: QuestionTopic
    category: str
    topic: str
    source_urls: tuple[str, ...]
    source_evidence: tuple[str, ...]


@dataclass(frozen=True)
class StoredQuestion:
    """Persisted question record."""

    game_date: str
    prompt: str
    options: dict[str, str]
    correct_option: str
    source_note: str
    source_url: str
    source: str
    gmail_message_id: str
    created_at: str

    @classmethod
    def from_record(cls, record: dict[str, Any]) -> StoredQuestion:
        """Create a stored question from a persistent storage record."""

        return cls(
            game_date=str(record["game_date"]),
            prompt=str(record["prompt"]),
            options=dict(record["options"]),
            correct_option=str(record["correct_option"]),
            source_note=str(record["source_note"]),
            source_url=str(record["source_url"]),
            source=str(record["source"]),
            gmail_message_id=str(record["gmail_message_id"]),
            created_at=str(record["created_at"]),
        )

    @classmethod
    def from_question(cls, question: Question, gmail_message_id: str, created_at: datetime) -> StoredQuestion:
        """Create a persisted record from a generated question."""

        return cls(
            game_date=question.game_date,
            prompt=question.prompt,
            options=question.options,
            correct_option=question.correct_option,
            source_note=question.source_note,
            source_url=question.source_url,
            source=question.source,
            gmail_message_id=gmail_message_id,
            created_at=created_at.isoformat(),
        )

    def to_json_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""

        return asdict(self)
@dataclass(frozen=True)
class ScoreboardLine:
    """One Player's Score in a Series, as shown on the Scoreboard."""

    series: str
    email: str
    points: int
    nickname: str | None = None

    def to_json_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""

        return asdict(self)


@dataclass(frozen=True)
class SubmissionCandidate:
    """Reply data that can later be interpreted and scored."""

    game_date: str
    sender_email: str
    gmail_message_id: str
    received_at: str
    body_text: str

    @property
    def processing_key(self) -> str:
        """Return an idempotency key for this sender and game date."""

        return f"{self.game_date}:{self.sender_email}"


@dataclass(frozen=True)
class ManualScoreEvent:
    """Persisted manual Score Event created by an Organizer Instruction."""

    series: str
    email: str
    points_delta: int
    source_gmail_message_id: str
    idempotency_key: str
    reason: str
    created_at: str

    def to_json_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""

        return asdict(self)
