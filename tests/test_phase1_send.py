from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path

from qotd.emailing import build_participant_email
from qotd.generator import generate_placeholder_question
from qotd.storage import read_question_records
from qotd.validation import validate_question
from qotd.workflow import SendQuestionConfig, send_question


class Phase1SendTests(unittest.TestCase):
    def test_placeholder_question_matches_contract(self) -> None:
        question = generate_placeholder_question("2026-07-09")

        validate_question(question)
        self.assertEqual(set(question.options), {"A", "B", "C", "D"})
        self.assertEqual(question.correct_option, "B")
        self.assertTrue(question.source_url.startswith("https://"))

    def test_participant_email_omits_answer_metadata(self) -> None:
        question = generate_placeholder_question("2026-07-09")
        message = build_participant_email(question, "***SECRET***", "players@example.com")
        body = message.get_content()

        self.assertIn(question.prompt, body)
        self.assertIn("A. Mars", body)
        self.assertIn("B. Jupiter", body)
        self.assertIn("D. Neptune", body)
        self.assertNotIn("Correct answer", body)
        self.assertNotIn(question.source_url, body)
        self.assertNotIn(question.source_note, body)

    def test_dry_run_send_persists_question_record(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "questions.jsonl"

            result = send_question(
                SendQuestionConfig(
                    game_date=date(2026, 7, 9),
                    sender="***SECRET***",
                    mailing_list="players@example.com",
                    state_path=state_path,
                    delegated_user="***SECRET***",
                    service_account_file="",
                    dry_run=True,
                )
            )

            records = read_question_records(state_path)
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["game_date"], "2026-07-09")
            self.assertEqual(records[0]["gmail_message_id"], "dry-run:2026-07-09")
            self.assertEqual(records[0]["correct_option"], "B")
            self.assertIn(result.record.prompt, result.email_body)


if __name__ == "__main__":
    unittest.main()
