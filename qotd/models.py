"""Core data contracts for QOTD workflows."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any


OPTION_LABELS = ("A", "B", "C", "D")


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

