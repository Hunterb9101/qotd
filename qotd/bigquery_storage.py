"""BigQuery-backed state for QOTD workflows."""

from __future__ import annotations

import importlib
import json
from datetime import UTC, datetime
from typing import Any

from qotd.auth import build_oauth_credentials
from qotd.models import CorrectAnswerUpdate, ManualAdjustment, MonthlyScore, ReplyProcessingRecord, StoredQuestion


BIGQUERY_SCOPE = "https://www.googleapis.com/auth/bigquery"


class BigQueryStateStore:
    """BigQuery-backed append-only QOTD state store."""

    def __init__(self, *, project_id: str, dataset: str, client: Any) -> None:
        self.project_id = project_id
        self.dataset = dataset
        self.client = client

    @classmethod
    def from_oauth(
        cls,
        *,
        project_id: str,
        dataset: str,
        oauth_client_id: str,
        oauth_client_secret: str,
        oauth_refresh_token: str,
    ) -> BigQueryStateStore:
        """Build a BigQuery state store from OAuth user credentials."""

        bigquery = importlib.import_module("google.cloud.bigquery")
        credentials = build_oauth_credentials(
            client_id=oauth_client_id,
            client_secret=oauth_client_secret,
            refresh_token=oauth_refresh_token,
            scopes=[BIGQUERY_SCOPE],
        )
        return cls(
            project_id=project_id,
            dataset=dataset,
            client=bigquery.Client(project=project_id, credentials=credentials),
        )

    def table(self, name: str) -> str:
        """Return a fully qualified table id."""

        return f"{self.project_id}.{self.dataset}.{name}"

    def insert_rows(self, table_name: str, rows: list[dict[str, Any]]) -> None:
        """Insert rows and raise a useful error if BigQuery rejects them."""

        errors = self.client.insert_rows_json(self.table(table_name), rows)
        if errors:
            raise RuntimeError(f"BigQuery insert failed for {table_name}: {errors}")

    def query_rows(self, query: str, parameters: list[Any] | None = None) -> list[dict[str, Any]]:
        """Run a parameterized query and return dict rows."""

        bigquery = importlib.import_module("google.cloud.bigquery")
        job_config = bigquery.QueryJobConfig(query_parameters=parameters or [])
        return [dict(row.items()) for row in self.client.query(query, job_config=job_config).result()]

    def append_question_record(self, record: StoredQuestion) -> None:
        """Append one question record."""

        self.insert_rows(
            "questions",
            [
                {
                    "game_date": record.game_date,
                    "prompt": record.prompt,
                    "options": record.options,
                    "correct_option": record.correct_option,
                    "source_note": record.source_note,
                    "source_url": record.source_url,
                    "source": record.source,
                    "gmail_message_id": record.gmail_message_id,
                    "created_at": record.created_at,
                }
            ],
        )

    def read_question_records(self) -> list[dict[str, Any]]:
        """Read question records."""

        records = self.query_rows(
            f"""
            SELECT
              CAST(game_date AS STRING) AS game_date,
              prompt,
              TO_JSON_STRING(options) AS options,
              correct_option,
              source_note,
              source_url,
              source,
              gmail_message_id,
              CAST(created_at AS STRING) AS created_at
            FROM `{self.table("questions")}`
            ORDER BY created_at
            """
        )
        for record in records:
            options = record.get("options")
            if isinstance(options, str):
                record["options"] = json.loads(options)
        return records

    def append_monthly_score(self, record: MonthlyScore) -> None:
        """Append one monthly score record."""

        self.insert_rows(
            "monthly_scores",
            [
                {
                    "series": record.series,
                    "email": record.email,
                    "points": record.points,
                    "updated_at": datetime.now(UTC).isoformat(),
                }
            ],
        )

    def read_monthly_scores(self, *, series: str | None = None) -> list[dict[str, Any]]:
        """Read monthly score records."""

        parameters = []
        where_clause = ""
        if series is not None:
            bigquery = importlib.import_module("google.cloud.bigquery")
            where_clause = "WHERE series = @series"
            parameters.append(bigquery.ScalarQueryParameter("series", "STRING", series))
        return self.query_rows(
            f"""
            SELECT series, email, points
            FROM `{self.table("monthly_scores")}`
            {where_clause}
            ORDER BY updated_at
            """,
            parameters,
        )

    def append_reply_processing_record(
        self,
        record: ReplyProcessingRecord,
        *,
        interpreted_option: str | None = None,
    ) -> None:
        """Append one reply-processing record."""

        self.insert_rows(
            "reply_processing",
            [
                {
                    "game_date": record.game_date,
                    "email": record.email,
                    "processing_key": record.processing_key,
                    "latest_gmail_message_id": record.latest_gmail_message_id,
                    "interpreted_option": interpreted_option,
                    "points_awarded": record.points_awarded,
                    "needs_audit": record.needs_audit,
                    "processed_at": record.processed_at,
                }
            ],
        )

    def read_reply_processing_records(self, *, game_date: str | None = None) -> list[dict[str, Any]]:
        """Read reply-processing records."""

        parameters = []
        where_clause = ""
        if game_date is not None:
            bigquery = importlib.import_module("google.cloud.bigquery")
            where_clause = "WHERE game_date = @game_date"
            parameters.append(bigquery.ScalarQueryParameter("game_date", "DATE", game_date))
        return self.query_rows(
            f"""
            SELECT
              CAST(game_date AS STRING) AS game_date,
              email,
              processing_key,
              latest_gmail_message_id,
              interpreted_option,
              points_awarded,
              needs_audit,
              CAST(processed_at AS STRING) AS processed_at
            FROM `{self.table("reply_processing")}`
            {where_clause}
            ORDER BY processed_at
            """,
            parameters,
        )

    def append_manual_adjustment(self, record: ManualAdjustment) -> None:
        """Append one manual adjustment record."""

        self.insert_rows("manual_adjustments", [record.to_json_dict()])

    def read_manual_adjustments(self) -> list[dict[str, Any]]:
        """Read manual adjustment records."""

        return self.query_rows(f"SELECT * FROM `{self.table('manual_adjustments')}` ORDER BY created_at")

    def append_correct_answer_update(self, record: CorrectAnswerUpdate) -> None:
        """Append one correct-answer update record."""

        self.insert_rows("correct_answer_updates", [record.to_json_dict()])

    def read_correct_answer_updates(self, *, game_date: str | None = None) -> list[dict[str, Any]]:
        """Read correct-answer update records."""

        parameters = []
        where_clause = ""
        if game_date is not None:
            bigquery = importlib.import_module("google.cloud.bigquery")
            where_clause = "WHERE game_date = @game_date"
            parameters.append(bigquery.ScalarQueryParameter("game_date", "DATE", game_date))
        return self.query_rows(
            f"SELECT * FROM `{self.table('correct_answer_updates')}` {where_clause} ORDER BY created_at",
            parameters,
        )
