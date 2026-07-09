"""Persistent state interfaces for QOTD records."""

from __future__ import annotations

from typing import Any, Protocol

from qotd.models import CorrectAnswerUpdate, ManualAdjustment, MonthlyScore, ReplyProcessingRecord, StoredQuestion


class StateStore(Protocol):
    """Persistent state backend for QOTD workflows."""

    def append_question_record(self, record: StoredQuestion) -> None:
        """Append one question record."""

    def read_question_records(self) -> list[dict[str, Any]]:
        """Read question records."""

    def append_monthly_score(self, record: MonthlyScore) -> None:
        """Append one monthly score record."""

    def read_monthly_scores(self, *, series: str | None = None) -> list[dict[str, Any]]:
        """Read monthly score records."""

    def append_reply_processing_record(
        self,
        record: ReplyProcessingRecord,
        *,
        interpreted_option: str | None = None,
    ) -> None:
        """Append one reply-processing record."""

    def read_reply_processing_records(self, *, game_date: str | None = None) -> list[dict[str, Any]]:
        """Read reply-processing records."""

    def append_manual_adjustment(self, record: ManualAdjustment) -> None:
        """Append one manual adjustment record."""

    def read_manual_adjustments(self) -> list[dict[str, Any]]:
        """Read manual adjustment records."""

    def append_correct_answer_update(self, record: CorrectAnswerUpdate) -> None:
        """Append one correct-answer update record."""

    def read_correct_answer_updates(self, *, game_date: str | None = None) -> list[dict[str, Any]]:
        """Read correct-answer update records."""
