from __future__ import annotations

import base64
import unittest
from datetime import date, datetime

from qotd.models import StoredQuestion
from qotd.response_workflow import (
    ScoreResponsesConfig,
    collect_reply_candidates,
    gmail_reply_query,
    score_responses,
)
from tests.support import InMemoryStateStore


def stored_question() -> StoredQuestion:
    """Build a stored question fixture."""

    return StoredQuestion(
        game_date="2026-07-09",
        prompt="Which planet has the Great Red Spot?",
        options={"A": "Mars", "B": "Jupiter", "C": "Saturn", "D": "Neptune"},
        correct_option="B",
        source_note="Jupiter has the Great Red Spot.",
        source_url="https://example.com/jupiter",
        source="generated",
        gmail_message_id="question-1",
        created_at="2026-07-09T18:00:00+00:00",
    )


def gmail_body_data(text: str) -> str:
    """Encode text using Gmail API body encoding."""

    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("ascii").rstrip("=")


def gmail_message(
    *,
    message_id: str,
    sender: str,
    body: str,
    sent_at: datetime,
) -> dict[str, object]:
    """Build a minimal Gmail API message fixture."""

    return {
        "id": message_id,
        "threadId": "thread-1",
        "internalDate": str(int(sent_at.timestamp() * 1000)),
        "payload": {
            "headers": [
                {"name": "From", "value": sender},
                {"name": "Subject", "value": "Re: QOTD"},
            ],
            "body": {"data": gmail_body_data(body)},
            "mimeType": "text/plain",
        },
    }


class ResponseWorkflowTests(unittest.TestCase):
    def test_gmail_reply_query_uses_game_and_scoring_dates(self) -> None:
        query = gmail_reply_query(game_date=date(2026, 7, 9), scoring_date=date(2026, 7, 10))

        self.assertEqual(query, "subject:QOTD after:2026/07/09 before:2026/07/11")

    def test_collect_reply_candidates_excludes_sender_and_presend_messages(self) -> None:
        messages = [
            gmail_message(
                message_id="sent-question",
                sender="***SECRET***",
                body="Question",
                sent_at=datetime.fromisoformat("2026-07-09T18:01:00+00:00"),
            ),
            gmail_message(
                message_id="too-early",
                sender="player@example.com",
                body="B",
                sent_at=datetime.fromisoformat("2026-07-09T17:00:00+00:00"),
            ),
            gmail_message(
                message_id="reply-1",
                sender="player@example.com",
                body="B",
                sent_at=datetime.fromisoformat("2026-07-09T19:00:00+00:00"),
            ),
        ]

        replies = collect_reply_candidates(messages, question=stored_question(), sender="***SECRET***")

        self.assertEqual(len(replies), 1)
        self.assertEqual(replies[0].gmail_message_id, "reply-1")

    def test_score_responses_dry_run_scores_fetched_gmail_messages(self) -> None:
        store = InMemoryStateStore()
        store.append_question_record(stored_question())

        result = score_responses(
            ScoreResponsesConfig(
                scoring_date=date(2026, 7, 10),
                sender="***SECRET***",
                organizer="***SECRET***",
                gmail_user="***SECRET***",
                oauth_client_id="client-id",
                oauth_client_secret="client-secret",
                oauth_refresh_token="refresh-token",
                state_store=store,
                dry_run=True,
            ),
            fetch_messages=lambda _query: [
                gmail_message(
                    message_id="reply-1",
                    sender="player@example.com",
                    body="B",
                    sent_at=datetime.fromisoformat("2026-07-10T12:30:00+00:00"),
                )
            ],
        )

        self.assertEqual(result.reply_count, 1)
        self.assertEqual(result.organizer_message_id, "dry-run:2026-07-09")
        self.assertIn("player@example.com", result.organizer_update_body)
        self.assertEqual(store.read_monthly_scores()[0]["points"], 1)
        self.assertEqual(
            store.read_reply_processing_records()[0]["processing_key"],
            "2026-07-09:player@example.com",
        )

    def test_score_responses_can_score_explicit_game_date(self) -> None:
        store = InMemoryStateStore()
        store.append_question_record(stored_question())

        result = score_responses(
            ScoreResponsesConfig(
                scoring_date=None,
                game_date=date(2026, 7, 9),
                sender="***SECRET***",
                organizer="***SECRET***",
                gmail_user="***SECRET***",
                oauth_client_id="client-id",
                oauth_client_secret="client-secret",
                oauth_refresh_token="refresh-token",
                state_store=store,
                dry_run=True,
            ),
            fetch_messages=lambda _query: [
                gmail_message(
                    message_id="reply-1",
                    sender="player@example.com",
                    body="B",
                    sent_at=datetime.fromisoformat("2026-07-10T12:30:00+00:00"),
                )
            ],
        )

        self.assertEqual(result.question.game_date, "2026-07-09")
        self.assertEqual(result.gmail_query, "subject:QOTD after:2026/07/09 before:2026/07/11")
        self.assertEqual(result.organizer_message_id, "dry-run:2026-07-09")


if __name__ == "__main__":
    unittest.main()
