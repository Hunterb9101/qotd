"""Implementation-agnostic persistent storage client contract."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from qotd.domain.models import CorrectAnswerUpdate, ManualAdjustment, MonthlyScore, ReplyProcessingRecord, StoredQuestion


class StorageClient(ABC):
    """Persistent state backend for QOTD workflows."""

    @abstractmethod
    def append_question_record(self, record: StoredQuestion) -> None:
        """Append one question record."""

    @abstractmethod
    def read_question_records(self) -> list[dict[str, Any]]:
        """Read question records."""

    @abstractmethod
    def append_monthly_score(self, record: MonthlyScore) -> None:
        """Append one monthly score record."""

    @abstractmethod
    def read_monthly_scores(self, *, series: str | None = None) -> list[dict[str, Any]]:
        """Read monthly score records."""

    @abstractmethod
    def append_reply_processing_record(
        self,
        record: ReplyProcessingRecord,
        *,
        interpreted_option: str | None = None,
    ) -> None:
        """Append one reply-processing record."""

    @abstractmethod
    def read_reply_processing_records(self, *, game_date: str | None = None) -> list[dict[str, Any]]:
        """Read reply-processing records."""

    @abstractmethod
    def append_manual_adjustment(self, record: ManualAdjustment) -> None:
        """Append one manual adjustment record."""

    @abstractmethod
    def read_manual_adjustments(self) -> list[dict[str, Any]]:
        """Read manual adjustment records."""

    @abstractmethod
    def append_correct_answer_update(self, record: CorrectAnswerUpdate) -> None:
        """Append one correct-answer update record."""

    @abstractmethod
    def read_correct_answer_updates(self, *, game_date: str | None = None) -> list[dict[str, Any]]:
        """Read correct-answer update records."""
