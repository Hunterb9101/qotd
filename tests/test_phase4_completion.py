from __future__ import annotations

import unittest
from datetime import UTC, date, datetime
from email.message import EmailMessage

from qotd.domain.dates import is_final_weekday_of_month
from qotd.domain.models import StoredQuestion
from qotd.external.email.core import ParsedEmailMessage
from qotd.presentation.organizer_updates import build_organizer_update_body
from qotd.usecases.correct_answer import (
    ProcessCorrectAnswerEmailsConfig,
    parse_correct_answer_email,
    process_correct_answer_emails,
)
from qotd.usecases.score_responses import ScoreResponsesConfig, load_question_for_game_date, score_responses
from qotd.usecases.send_question import SendQuestionConfig, cody_sent_query, send_question
from tests.support import InMemoryStateStore


def stored_question(*, correct_option: str = "B", source: str = "generated") -> StoredQuestion:
    """Build a stored question fixture."""

    return StoredQuestion(
        game_date="2026-07-09",
        prompt="Which planet has the Great Red Spot?",
        options={"A": "Mars", "B": "Jupiter", "C": "Saturn", "D": "Neptune"} if correct_option else {},
        correct_option=correct_option,
        source_note="Jupiter has the Great Red Spot.",
        source_url="https://example.com/jupiter" if correct_option else "",
        source=source,
        gmail_message_id="question-1",
        created_at="2026-07-09T18:00:00+00:00",
    )


class Phase4CompletionTests(unittest.TestCase):
    def test_final_weekday_detection_handles_weekend_month_end(self) -> None:
        self.assertTrue(is_final_weekday_of_month(date(2026, 7, 31)))
        self.assertTrue(is_final_weekday_of_month(date(2026, 10, 30)))
        self.assertFalse(is_final_weekday_of_month(date(2026, 10, 29)))

    def test_cody_sent_question_is_stored_and_generated_send_is_skipped(self) -> None:
        store = InMemoryStateStore()

        result = send_question(
            SendQuestionConfig(
                game_date=date(2026, 7, 9),
                sender="sender@example.com",
                contact_group_name="QOTD Participants",
                gmail_user="sender@example.com",
                oauth_client_id="client-id",
                oauth_client_secret="client-secret",
                oauth_refresh_token="refresh-token",
                state_store=store,
                dry_run=False,
            ),
            fetch_messages=lambda query: [
                ParsedEmailMessage(
                    message_id="manual-1",
                    thread_id="thread-1",
                    sender_email="sender@example.com",
                    subject="QOTD - 2026-07-09",
                    sent_at=datetime(2026, 7, 9, 18, 0, tzinfo=UTC),
                    body_text="Manual question body",
                )
            ]
            if query == cody_sent_query(sender="sender@example.com", game_date=date(2026, 7, 9))
            else [],
        )

        self.assertTrue(result.skipped_generated_send)
        self.assertEqual(result.record.source, "manual")
        self.assertEqual(result.record.correct_option, "")
        self.assertEqual(store.read_question_records()[0]["gmail_message_id"], "manual-1")

    def test_correct_answer_email_is_parsed_and_applied(self) -> None:
        store = InMemoryStateStore()
        store.append_question_record(stored_question(correct_option="", source="manual"))
        sent_messages: list[EmailMessage] = []
        handled: list[str] = []

        def send_confirmation(message: EmailMessage) -> str:
            sent_messages.append(message)
            return "confirmation-1"

        parsed = parse_correct_answer_email(
            """
            Action: set-correct-answer
            Game date: 2026-07-09
            Correct option: C
            Source URL: https://example.com/source
            """
        )
        self.assertEqual(parsed.correct_option, "C")

        result = process_correct_answer_emails(
            ProcessCorrectAnswerEmailsConfig(
                sender="sender@example.com",
                gmail_user="sender@example.com",
                organizer_emails=("organizer@example.com",),
                oauth_client_id="client-id",
                oauth_client_secret="client-secret",
                oauth_refresh_token="refresh-token",
                state_store=store,
            ),
            fetch_messages=lambda _query: [
                ParsedEmailMessage(
                    message_id="answer-1",
                    thread_id="thread-1",
                    sender_email="organizer@example.com",
                    subject="Correct answer",
                    sent_at=datetime(2026, 7, 10, 13, 45, tzinfo=UTC),
                    body_text=(
                        "Action: set-correct-answer\n"
                        "Game date: 2026-07-09\n"
                        "Correct option: C\n"
                        "Source URL: https://example.com/source\n"
                    ),
                )
            ],
            send_message=send_confirmation,
            mark_message_handled=handled.append,
        )

        self.assertTrue(result.processed[0].accepted)
        self.assertEqual(store.read_correct_answer_updates()[0]["correct_option"], "C")
        self.assertEqual(handled, ["answer-1"])
        self.assertIn("Applied correct answer update", sent_messages[0].get_content())

    def test_scoring_uses_latest_correct_answer_update(self) -> None:
        store = InMemoryStateStore()
        store.append_question_record(stored_question(correct_option="B"))
        process_correct_answer_emails(
            ProcessCorrectAnswerEmailsConfig(
                sender="sender@example.com",
                gmail_user="sender@example.com",
                organizer_emails=("organizer@example.com",),
                oauth_client_id="client-id",
                oauth_client_secret="client-secret",
                oauth_refresh_token="refresh-token",
                state_store=store,
                dry_run=False,
            ),
            fetch_messages=lambda _query: [
                ParsedEmailMessage(
                    message_id="answer-1",
                    thread_id="thread-1",
                    sender_email="organizer@example.com",
                    subject="Correct answer",
                    sent_at=datetime(2026, 7, 10, 13, 45, tzinfo=UTC),
                    body_text=(
                        "Action: set-correct-answer\n"
                        "Game date: 2026-07-09\n"
                        "Correct option: C\n"
                        "Source URL: https://example.com/source\n"
                    ),
                )
            ],
            send_message=lambda _message: "confirmation-1",
            mark_message_handled=lambda _message_id: None,
        )

        loaded = load_question_for_game_date(store, date(2026, 7, 9))

        self.assertEqual(loaded.correct_option, "C")
        self.assertEqual(loaded.source_url, "https://example.com/source")

    def test_manual_question_without_correct_answer_skips_scoring_with_alert(self) -> None:
        store = InMemoryStateStore()
        store.append_question_record(stored_question(correct_option="", source="manual"))

        result = score_responses(
            ScoreResponsesConfig(
                scoring_date=date(2026, 7, 10),
                sender="sender@example.com",
                organizer="organizer@example.com",
                gmail_user="sender@example.com",
                oauth_client_id="client-id",
                oauth_client_secret="client-secret",
                oauth_refresh_token="refresh-token",
                state_store=store,
                dry_run=True,
            )
        )

        self.assertEqual(result.skipped_reason, "missing_correct_answer")
        self.assertIn("Action: set-correct-answer", result.organizer_update_body)
        self.assertEqual(store.read_monthly_scores(), [])

    def test_organizer_update_includes_review_template_and_winner_notice(self) -> None:
        from qotd.domain.scoring import ScoredReply, ScoringResult
        from qotd.domain.models import MonthlyScore

        body = build_organizer_update_body(
            StoredQuestion(
                game_date="2026-07-31",
                prompt="Question?",
                options={"A": "One", "B": "Two", "C": "Three", "D": "Four"},
                correct_option="A",
                source_note="Note",
                source_url="https://example.com",
                source="generated",
                gmail_message_id="question-1",
                created_at="2026-07-31T18:00:00+00:00",
            ),
            ScoringResult(
                game_date="2026-07-31",
                correct=(),
                incorrect=(),
                needs_review=(
                    ScoredReply(
                        email="review@example.com",
                        gmail_message_id="reply-1",
                        interpreted_option="UNKNOWN",
                        points_awarded=0,
                        needs_review=True,
                    ),
                ),
                skipped_processing_keys=(),
                standings=(MonthlyScore(series="0726", email="winner@example.com", points=4),),
            ),
        )

        self.assertIn("Action: adjust-score", body)
        self.assertIn("Gmail message ID: reply-1", body)
        self.assertIn("Monthly winner announcement", body)
        self.assertIn("winner@example.com", body)


if __name__ == "__main__":
    unittest.main()
