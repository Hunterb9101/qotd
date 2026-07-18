from __future__ import annotations

import unittest
from datetime import datetime

from qotd.domain.models import MonthlyScore, ReplyCandidate, StoredQuestion
from qotd.domain.scoring import (
    AnswerInterpretation,
    ScoringResult,
    parse_deterministic_answer,
    score_replies,
    select_latest_eligible_replies,
)
from qotd.presentation.emails import build_organizer_email
from qotd.presentation.organizer_updates import build_organizer_update_body
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


def persist_scoring_updates(store: InMemoryStateStore, result: ScoringResult) -> None:
    """Persist scoring updates produced by domain scoring."""

    for score_record in result.monthly_score_updates:
        store.append_monthly_score(score_record)
    for processing_update in result.reply_processing_updates:
        store.append_reply_processing_record(
            processing_update.record,
            interpreted_option=processing_update.interpreted_option,
        )


class Phase3ScoringTests(unittest.TestCase):
    def test_deterministic_answer_parsing_accepts_only_single_option(self) -> None:
        self.assertEqual(parse_deterministic_answer(" b ").option, "B")

        freeform = parse_deterministic_answer("I think it is B")
        self.assertEqual(freeform.option, "UNKNOWN")
        self.assertTrue(freeform.needs_review)

    def test_latest_eligible_reply_is_selected_before_cutoff(self) -> None:
        replies = [
            ReplyCandidate(
                game_date="2026-07-09",
                sender_email="player@example.com",
                gmail_message_id="old",
                received_at="2026-07-10T06:00:00-06:00",
                body_text="A",
            ),
            ReplyCandidate(
                game_date="2026-07-09",
                sender_email="player@example.com",
                gmail_message_id="latest",
                received_at="2026-07-10T06:59:00-06:00",
                body_text="B",
            ),
            ReplyCandidate(
                game_date="2026-07-09",
                sender_email="player@example.com",
                gmail_message_id="late",
                received_at="2026-07-10T07:00:00-06:00",
                body_text="C",
            ),
        ]

        selected = select_latest_eligible_replies(
            replies,
            cutoff_at=datetime.fromisoformat("2026-07-10T07:00:00-06:00"),
        )

        self.assertEqual(selected["player@example.com"].gmail_message_id, "latest")

    def test_score_replies_persists_scores_and_skips_reruns(self) -> None:
        store = InMemoryStateStore()
        question = stored_question()
        replies = [
            ReplyCandidate(
                game_date="2026-07-09",
                sender_email="correct@example.com",
                gmail_message_id="reply-1",
                received_at="2026-07-10T06:30:00-06:00",
                body_text="B",
            ),
            ReplyCandidate(
                game_date="2026-07-09",
                sender_email="wrong@example.com",
                gmail_message_id="reply-2",
                received_at="2026-07-10T06:30:00-06:00",
                body_text="A",
            ),
            ReplyCandidate(
                game_date="2026-07-09",
                sender_email="review@example.com",
                gmail_message_id="reply-3",
                received_at="2026-07-10T06:30:00-06:00",
                body_text="Probably Jupiter",
            ),
        ]

        result = score_replies(
            question=question,
            replies=replies,
            cutoff_at=datetime.fromisoformat("2026-07-10T07:00:00-06:00"),
            processed_at=datetime.fromisoformat("2026-07-10T14:00:00+00:00"),
            existing_reply_processing_records=store.read_reply_processing_records(game_date=question.game_date),
            existing_monthly_score_records=store.read_monthly_scores(),
        )
        persist_scoring_updates(store, result)
        rerun = score_replies(
            question=question,
            replies=replies,
            cutoff_at=datetime.fromisoformat("2026-07-10T07:00:00-06:00"),
            processed_at=datetime.fromisoformat("2026-07-10T14:05:00+00:00"),
            existing_reply_processing_records=store.read_reply_processing_records(game_date=question.game_date),
            existing_monthly_score_records=store.read_monthly_scores(),
        )

        self.assertEqual([reply.email for reply in result.correct], ["correct@example.com"])
        self.assertEqual([reply.email for reply in result.incorrect], ["wrong@example.com"])
        self.assertEqual([reply.email for reply in result.needs_review], ["review@example.com"])
        self.assertEqual(len(rerun.skipped_processing_keys), 3)
        self.assertEqual(len(store.read_reply_processing_records()), 3)
        score_rows = store.read_monthly_scores()
        self.assertEqual(len(score_rows), 1)
        self.assertEqual(score_rows[0]["points"], 1)

    def test_existing_score_totals_are_incremented(self) -> None:
        store = InMemoryStateStore()
        store.append_monthly_score(MonthlyScore(series="0726", email="correct@example.com", points=4))

        result = score_replies(
            question=stored_question(),
            replies=[
                ReplyCandidate(
                    game_date="2026-07-09",
                    sender_email="correct@example.com",
                    gmail_message_id="reply-1",
                    received_at="2026-07-10T06:30:00-06:00",
                    body_text="B",
                )
            ],
            cutoff_at=datetime.fromisoformat("2026-07-10T07:00:00-06:00"),
            processed_at=datetime.fromisoformat("2026-07-10T14:00:00+00:00"),
            existing_reply_processing_records=store.read_reply_processing_records(game_date=stored_question().game_date),
            existing_monthly_score_records=store.read_monthly_scores(),
        )

        self.assertEqual(result.standings[0].points, 5)

    def test_custom_answer_interpreter_can_handle_freeform_replies(self) -> None:
        result = score_replies(
            question=stored_question(),
            replies=[
                ReplyCandidate(
                    game_date="2026-07-09",
                    sender_email="freeform@example.com",
                    gmail_message_id="reply-1",
                    received_at="2026-07-10T06:30:00-06:00",
                    body_text="Probably Jupiter",
                )
            ],
            cutoff_at=datetime.fromisoformat("2026-07-10T07:00:00-06:00"),
            processed_at=datetime.fromisoformat("2026-07-10T14:00:00+00:00"),
            interpret_answer=lambda _text: AnswerInterpretation(option="B", needs_review=False),
        )

        self.assertEqual(result.correct[0].email, "freeform@example.com")

    def test_correlated_replies_are_scored_without_a_separate_eligibility_list(self) -> None:
        result = score_replies(
            question=stored_question(),
            replies=[
                ReplyCandidate(
                    game_date="2026-07-09",
                    sender_email="member@example.com",
                    gmail_message_id="reply-1",
                    received_at="2026-07-10T06:30:00-06:00",
                    body_text="B",
                ),
                ReplyCandidate(
                    game_date="2026-07-09",
                    sender_email="unknown@example.com",
                    gmail_message_id="reply-2",
                    received_at="2026-07-10T06:31:00-06:00",
                    body_text="B",
                ),
            ],
            cutoff_at=datetime.fromisoformat("2026-07-10T07:00:00-06:00"),
            processed_at=datetime.fromisoformat("2026-07-10T14:00:00+00:00"),
        )

        self.assertEqual(
            [reply.email for reply in result.correct],
            ["member@example.com", "unknown@example.com"],
        )
        self.assertEqual(result.no_response, ())
        self.assertEqual(result.ineligible_senders, ())
        self.assertEqual(
            [(standing.email, standing.points) for standing in result.standings],
            [("member@example.com", 1), ("unknown@example.com", 1)],
        )
        body = build_organizer_update_body(stored_question(), result)
        self.assertNotIn("Ineligible senders", body)
        self.assertIn("unknown@example.com", body)

    def test_organizer_update_body_contains_scoring_sections(self) -> None:
        result = score_replies(
            question=stored_question(),
            replies=[
                ReplyCandidate(
                    game_date="2026-07-09",
                    sender_email="correct@example.com",
                    gmail_message_id="reply-1",
                    received_at="2026-07-10T06:30:00-06:00",
                    body_text="B",
                )
            ],
            cutoff_at=datetime.fromisoformat("2026-07-10T07:00:00-06:00"),
            processed_at=datetime.fromisoformat("2026-07-10T14:00:00+00:00"),
        )

        body = build_organizer_update_body(stored_question(), result)

        self.assertIn("Correct answer: B. Jupiter", body)
        self.assertIn("Correct replies:", body)
        self.assertIn("correct@example.com", body)
        self.assertIn("Current standings:", body)

    def test_organizer_email_wraps_scoring_update_body(self) -> None:
        message = build_organizer_email(
            sender="sender@example.com",
            organizer="organizer@example.com",
            subject="QOTD scoring update",
            body="Current standings:\n- player@example.com: 1",
        )

        self.assertEqual(message["To"], "organizer@example.com")
        self.assertEqual(message["From"], "sender@example.com")
        self.assertIn("Current standings", message.get_content())


if __name__ == "__main__":
    unittest.main()
