from __future__ import annotations

from typing import Any

from qotd.models import CorrectAnswerUpdate, ManualAdjustment, MonthlyScore, ReplyProcessingRecord, StoredQuestion


class InMemoryStateStore:
    """Test-only StateStore implementation."""

    def __init__(self) -> None:
        self.question_records: list[dict[str, Any]] = []
        self.monthly_score_records: list[dict[str, Any]] = []
        self.reply_processing_records: list[dict[str, Any]] = []
        self.manual_adjustment_records: list[dict[str, Any]] = []
        self.correct_answer_update_records: list[dict[str, Any]] = []

    def append_question_record(self, record: StoredQuestion) -> None:
        self.question_records.append(record.to_json_dict())

    def read_question_records(self) -> list[dict[str, Any]]:
        return list(self.question_records)

    def append_monthly_score(self, record: MonthlyScore) -> None:
        self.monthly_score_records.append(record.to_json_dict())

    def read_monthly_scores(self, *, series: str | None = None) -> list[dict[str, Any]]:
        records = self.monthly_score_records
        if series is not None:
            records = [record for record in records if record["series"] == series]
        return list(records)

    def append_reply_processing_record(
        self,
        record: ReplyProcessingRecord,
        *,
        interpreted_option: str | None = None,
    ) -> None:
        data = record.to_json_dict()
        data["interpreted_option"] = interpreted_option
        self.reply_processing_records.append(data)

    def read_reply_processing_records(self, *, game_date: str | None = None) -> list[dict[str, Any]]:
        records = self.reply_processing_records
        if game_date is not None:
            records = [record for record in records if record["game_date"] == game_date]
        return list(records)

    def append_manual_adjustment(self, record: ManualAdjustment) -> None:
        self.manual_adjustment_records.append(record.to_json_dict())

    def read_manual_adjustments(self) -> list[dict[str, Any]]:
        return list(self.manual_adjustment_records)

    def append_correct_answer_update(self, record: CorrectAnswerUpdate) -> None:
        self.correct_answer_update_records.append(record.to_json_dict())

    def read_correct_answer_updates(self, *, game_date: str | None = None) -> list[dict[str, Any]]:
        records = self.correct_answer_update_records
        if game_date is not None:
            records = [record for record in records if record["game_date"] == game_date]
        return list(records)
