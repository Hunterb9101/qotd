from __future__ import annotations

import base64
import unittest
from datetime import date, datetime
from email.message import EmailMessage

from qotd.dates import answer_cutoff_at, monthly_series, next_scoring_day, previous_game_day
from qotd.email_parsing import build_reply_candidate, parse_gmail_message, parse_rfc822_message
from qotd.models import MonthlyScore, ReplyProcessingRecord
from tests.support import InMemoryStateStore


def gmail_body_data(text: str) -> str:
    """Encode text using Gmail API body encoding."""

    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("ascii").rstrip("=")


class Phase2LocalDataTests(unittest.TestCase):
    def test_previous_game_day_skips_weekends(self) -> None:
        self.assertEqual(previous_game_day(date(2026, 7, 7)), date(2026, 7, 6))
        self.assertEqual(previous_game_day(date(2026, 7, 6)), date(2026, 7, 3))
        self.assertEqual(previous_game_day(date(2026, 7, 5)), date(2026, 7, 3))

    def test_next_scoring_day_skips_weekends(self) -> None:
        self.assertEqual(next_scoring_day(date(2026, 7, 9)), date(2026, 7, 10))
        self.assertEqual(next_scoring_day(date(2026, 7, 10)), date(2026, 7, 13))

    def test_answer_cutoff_is_mountain_time(self) -> None:
        cutoff = answer_cutoff_at(date(2026, 7, 9))

        self.assertEqual(cutoff.hour, 7)
        self.assertEqual(cutoff.minute, 0)
        self.assertEqual(cutoff.tzname(), "MDT")

    def test_monthly_series_uses_mm_yy(self) -> None:
        self.assertEqual(monthly_series(date(2026, 7, 9)), "0726")

    def test_state_records_round_trip_through_state_store(self) -> None:
        store = InMemoryStateStore()

        store.append_monthly_score(MonthlyScore(series="0726", email="player@example.com", points=2))
        store.append_reply_processing_record(
            ReplyProcessingRecord(
                game_date="2026-07-09",
                email="player@example.com",
                latest_gmail_message_id="gmail-1",
                points_awarded=1,
                needs_audit=False,
                processed_at="2026-07-10T14:00:00+00:00",
            )
        )

        self.assertEqual(store.read_monthly_scores()[0]["points"], 2)
        processing_record = store.read_reply_processing_records()[0]
        self.assertEqual(processing_record["processing_key"], "2026-07-09:player@example.com")
        self.assertEqual(processing_record["latest_gmail_message_id"], "gmail-1")

    def test_rfc822_message_parsing_normalizes_sender_and_strips_quotes(self) -> None:
        message = EmailMessage()
        message["From"] = "Player One <Player@Example.com>"
        message["Subject"] = "Re: QOTD"
        message["Message-ID"] = "message-1"
        message["Date"] = "Thu, 9 Jul 2026 06:45:00 -0600"
        message.set_content(" B \n\nOn Thu, QOTD wrote:\n> old question")

        parsed = parse_rfc822_message(message)
        reply = build_reply_candidate(parsed, game_date="2026-07-08")

        self.assertEqual(parsed.sender_email, "player@example.com")
        self.assertEqual(parsed.body_text, "B")
        self.assertEqual(reply.processing_key, "2026-07-08:player@example.com")
        self.assertEqual(reply.gmail_message_id, "message-1")

    def test_gmail_message_parsing_prefers_plain_text_payload(self) -> None:
        message = {
            "id": "gmail-1",
            "threadId": "thread-1",
            "internalDate": str(int(datetime(2026, 7, 9, 12, 45).timestamp() * 1000)),
            "payload": {
                "headers": [
                    {"name": "From", "value": "Player Two <two@example.com>"},
                    {"name": "Subject", "value": "Re: QOTD"},
                ],
                "parts": [
                    {
                        "mimeType": "text/html",
                        "body": {"data": gmail_body_data("<p>C</p>")},
                    },
                    {
                        "mimeType": "text/plain",
                        "body": {"data": gmail_body_data("C\n> quoted")},
                    },
                ],
            },
        }

        parsed = parse_gmail_message(message)

        self.assertEqual(parsed.message_id, "gmail-1")
        self.assertEqual(parsed.thread_id, "thread-1")
        self.assertEqual(parsed.sender_email, "two@example.com")
        self.assertEqual(parsed.body_text, "C")


if __name__ == "__main__":
    unittest.main()
