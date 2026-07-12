from __future__ import annotations

import unittest
from datetime import UTC, date, datetime
from email.message import EmailMessage
from unittest.mock import patch

from qotd.cli import build_parser
from qotd.domain.models import MonthlyScore, StoredQuestion
from qotd.external.email.core import ParsedEmailMessage
from qotd.usecases.adjust_score import (
    ProcessScoreAdjustmentEmailsConfig,
    ScoreAdjustmentConfig,
    apply_score_adjustment,
    parse_score_adjustment_email,
    process_score_adjustment_emails,
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


class Phase4ScoreAdjustmentTests(unittest.TestCase):
    def test_apply_score_adjustment_appends_audit_record_and_updated_score(self) -> None:
        store = InMemoryStateStore()
        store.append_question_record(stored_question())
        store.append_monthly_score(MonthlyScore(series="0726", email="player@example.com", points=2))

        with patch("qotd.usecases.adjust_score.datetime") as fake_datetime:
            fake_datetime.now.return_value.isoformat.return_value = "2026-07-10T14:00:00+00:00"
            result = apply_score_adjustment(
                ScoreAdjustmentConfig(
                    email=" Player@Example.com ",
                    game_date=date(2026, 7, 9),
                    points_delta=1,
                    reason="unclear_answer_accepted",
                    source_gmail_message_id="msg-123",
                    state_store=store,
                )
            )

        self.assertTrue(result.applied)
        self.assertEqual(result.monthly_score.points, 3)
        self.assertEqual(result.standings[0].email, "player@example.com")

        adjustment = store.read_manual_adjustments()[0]
        self.assertEqual(adjustment["series"], "0726")
        self.assertEqual(adjustment["email"], "player@example.com")
        self.assertEqual(adjustment["points_delta"], 1)
        self.assertEqual(adjustment["source_gmail_message_id"], "msg-123")
        self.assertEqual(adjustment["idempotency_key"], "manual:2026-07-09:player@example.com:unclear_answer_accepted")
        self.assertEqual(store.read_monthly_scores(series="0726")[-1]["points"], 3)

    def test_duplicate_adjustment_is_skipped_by_idempotency_key(self) -> None:
        store = InMemoryStateStore()
        store.append_question_record(stored_question())
        config = ScoreAdjustmentConfig(
            email="player@example.com",
            game_date=date(2026, 7, 9),
            points_delta=1,
            reason="unclear_answer_accepted",
            state_store=store,
        )

        first = apply_score_adjustment(config)
        second = apply_score_adjustment(config)

        self.assertTrue(first.applied)
        self.assertFalse(second.applied)
        self.assertEqual(second.monthly_score.points, 1)
        self.assertEqual(len(store.read_manual_adjustments()), 1)
        self.assertEqual(len(store.read_monthly_scores(series="0726")), 1)

    def test_series_adjustment_does_not_require_game_date(self) -> None:
        store = InMemoryStateStore()

        result = apply_score_adjustment(
            ScoreAdjustmentConfig(
                email="player@example.com",
                series="0726",
                points_delta=-1,
                reason="duplicate_correction",
                state_store=store,
            )
        )

        self.assertTrue(result.applied)
        self.assertEqual(result.adjustment.idempotency_key, "manual:0726:player@example.com:duplicate_correction")
        self.assertEqual(result.monthly_score.points, -1)

    def test_dry_run_returns_result_without_persisting(self) -> None:
        store = InMemoryStateStore()
        store.append_question_record(stored_question())

        result = apply_score_adjustment(
            ScoreAdjustmentConfig(
                email="player@example.com",
                game_date=date(2026, 7, 9),
                points_delta=1,
                reason="organizer_override",
                state_store=store,
                dry_run=True,
            )
        )

        self.assertTrue(result.applied)
        self.assertEqual(result.monthly_score.points, 1)
        self.assertEqual(store.read_manual_adjustments(), [])
        self.assertEqual(store.read_monthly_scores(), [])

    def test_date_adjustment_requires_stored_question(self) -> None:
        store = InMemoryStateStore()

        with self.assertRaisesRegex(ValueError, "no stored question exists"):
            apply_score_adjustment(
                ScoreAdjustmentConfig(
                    email="player@example.com",
                    game_date=date(2026, 7, 9),
                    points_delta=1,
                    reason="organizer_override",
                    state_store=store,
                )
            )

    def test_adjust_score_parser_accepts_documented_options(self) -> None:
        parser = build_parser()

        args = parser.parse_args(
            [
                "adjust-score",
                "--email",
                "person@example.com",
                "--date",
                "2026-07-08",
                "--points",
                "1",
                "--reason",
                "unclear_answer_accepted",
                "--gmail-message-id",
                "msg-123",
            ]
        )

        self.assertEqual(args.command, "adjust-score")
        self.assertEqual(args.game_date, date(2026, 7, 8))
        self.assertEqual(args.points_delta, 1)
        self.assertEqual(args.gmail_message_id, "msg-123")

    def test_parse_score_adjustment_email_accepts_template(self) -> None:
        request = parse_score_adjustment_email(
            """
            Action: adjust-score
            Participant: person@example.com
            Game date: 2026-07-09
            Points: 1
            Reason: unclear_answer_accepted
            Gmail message ID: msg_123
            """
        )

        self.assertEqual(request.participant_email, "person@example.com")
        self.assertEqual(request.game_date, date(2026, 7, 9))
        self.assertEqual(request.points_delta, 1)
        self.assertEqual(request.reason, "unclear_answer_accepted")
        self.assertEqual(request.source_gmail_message_id, "msg_123")

    def test_parse_score_adjustment_email_accepts_month(self) -> None:
        request = parse_score_adjustment_email(
            """
            Action: adjust-score
            Participant: person@example.com
            Month: 2026-07
            Points: -1
            Reason: duplicate_correction
            """
        )

        self.assertEqual(request.series, "0726")
        self.assertIsNone(request.game_date)

    def test_process_score_adjustment_emails_applies_approved_request_and_sends_confirmation(self) -> None:
        store = InMemoryStateStore()
        store.append_question_record(stored_question())
        sent_messages: list[EmailMessage] = []
        handled_message_ids: list[str] = []

        def send_confirmation(message: EmailMessage) -> str:
            sent_messages.append(message)
            return "confirmation-1"

        result = process_score_adjustment_emails(
            ProcessScoreAdjustmentEmailsConfig(
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
                    message_id="request-1",
                    thread_id="thread-1",
                    sender_email="Organizer@Example.com",
                    subject="Score correction",
                    sent_at=datetime(2026, 7, 10, 14, 0, tzinfo=UTC),
                    body_text=(
                        "Action: adjust-score\n"
                        "Participant: player@example.com\n"
                        "Game date: 2026-07-09\n"
                        "Points: 1\n"
                        "Reason: unclear_answer_accepted\n"
                        "Gmail message ID: reply-1\n"
                    ),
                )
            ],
            send_message=send_confirmation,
            mark_message_handled=handled_message_ids.append,
        )

        self.assertEqual(len(result.processed), 1)
        self.assertTrue(result.processed[0].accepted)
        self.assertEqual(result.processed[0].status, "applied")
        self.assertEqual(result.processed[0].response_message_id, "confirmation-1")
        self.assertEqual(store.read_manual_adjustments()[0]["source_gmail_message_id"], "reply-1")
        self.assertEqual(store.read_monthly_scores(series="0726")[0]["points"], 1)
        self.assertEqual(sent_messages[0]["To"], "organizer@example.com")
        self.assertIn("Applied score adjustment", sent_messages[0].get_content())
        self.assertEqual(handled_message_ids, ["request-1"])

    def test_process_score_adjustment_emails_rejects_unapproved_sender(self) -> None:
        store = InMemoryStateStore()
        sent_messages: list[EmailMessage] = []
        handled_message_ids: list[str] = []

        def send_rejection(message: EmailMessage) -> str:
            sent_messages.append(message)
            return "rejection-1"

        result = process_score_adjustment_emails(
            ProcessScoreAdjustmentEmailsConfig(
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
                    message_id="request-2",
                    thread_id="thread-2",
                    sender_email="stranger@example.com",
                    subject="Score correction",
                    sent_at=datetime(2026, 7, 10, 14, 0, tzinfo=UTC),
                    body_text="Action: adjust-score\nParticipant: player@example.com\n",
                )
            ],
            send_message=send_rejection,
            mark_message_handled=handled_message_ids.append,
        )

        self.assertFalse(result.processed[0].accepted)
        self.assertIn("sender is not approved", result.processed[0].status)
        self.assertEqual(store.read_manual_adjustments(), [])
        self.assertIn("request rejected", sent_messages[0].get_content())
        self.assertEqual(handled_message_ids, ["request-2"])

    def test_process_score_adjustments_parser_accepts_management_options(self) -> None:
        parser = build_parser()

        args = parser.parse_args(
            [
                "process-score-adjustments",
                "--organizer",
                "organizer@example.com",
                "--query",
                'is:unread "Action: adjust-score"',
                "--max-results",
                "10",
                "--dry-run",
            ]
        )

        self.assertEqual(args.command, "process-score-adjustments")
        self.assertEqual(args.organizer, ["organizer@example.com"])
        self.assertEqual(args.max_results, 10)
        self.assertTrue(args.dry_run)


if __name__ == "__main__":
    unittest.main()
