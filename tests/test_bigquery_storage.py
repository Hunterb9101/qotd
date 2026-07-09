from __future__ import annotations

import unittest
from datetime import UTC, datetime
from typing import Any

from qotd.bigquery_storage import BigQueryStateStore
from qotd.models import ReplyProcessingRecord, StoredQuestion


class FakeBigQueryClient:
    def __init__(self) -> None:
        self.inserted: list[tuple[str, list[dict[str, Any]]]] = []

    def insert_rows_json(self, table: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        self.inserted.append((table, rows))
        return []


class BigQueryStorageTests(unittest.TestCase):
    def test_append_question_record_writes_to_questions_table(self) -> None:
        client = FakeBigQueryClient()
        store = BigQueryStateStore(project_id="project-id", dataset="qotd", client=client)

        store.append_question_record(
            StoredQuestion(
                game_date="2026-07-09",
                prompt="Which planet has the Great Red Spot?",
                options={"A": "Mars", "B": "Jupiter", "C": "Saturn", "D": "Neptune"},
                correct_option="B",
                source_note="Jupiter has the Great Red Spot.",
                source_url="https://example.com/jupiter",
                source="generated",
                gmail_message_id="gmail-1",
                created_at=datetime(2026, 7, 9, 18, 0, tzinfo=UTC).isoformat(),
            )
        )

        table, rows = client.inserted[0]
        self.assertEqual(table, "project-id.qotd.questions")
        self.assertEqual(rows[0]["game_date"], "2026-07-09")
        self.assertEqual(rows[0]["options"]["B"], "Jupiter")

    def test_append_reply_processing_record_includes_interpreted_option(self) -> None:
        client = FakeBigQueryClient()
        store = BigQueryStateStore(project_id="project-id", dataset="qotd", client=client)

        store.append_reply_processing_record(
            ReplyProcessingRecord(
                game_date="2026-07-09",
                email="player@example.com",
                latest_gmail_message_id="gmail-2",
                points_awarded=1,
                needs_audit=False,
                processed_at="2026-07-10T14:00:00+00:00",
            ),
            interpreted_option="B",
        )

        table, rows = client.inserted[0]
        self.assertEqual(table, "project-id.qotd.reply_processing")
        self.assertEqual(rows[0]["processing_key"], "2026-07-09:player@example.com")
        self.assertEqual(rows[0]["interpreted_option"], "B")


if __name__ == "__main__":
    unittest.main()
