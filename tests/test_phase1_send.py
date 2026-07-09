from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path

from qotd.auth import GOOGLE_TOKEN_URI, build_oauth_credentials
from qotd.emailing import build_participant_email
from qotd.contacts import extract_email_addresses, find_contact_group, normalize_email_addresses
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
        message = build_participant_email(
            question,
            "***SECRET***",
            ["one@example.com", "two@example.com"],
        )
        body = message.get_content()

        self.assertEqual(message["To"], "***SECRET***")
        self.assertEqual(message["Bcc"], "one@example.com, two@example.com")
        self.assertIn(question.prompt, body)
        self.assertIn("A. Mars", body)
        self.assertIn("B. Jupiter", body)
        self.assertIn("D. Neptune", body)
        self.assertNotIn("Correct answer", body)
        self.assertNotIn(question.source_url, body)
        self.assertNotIn(question.source_note, body)

    def test_contact_group_matching_uses_exact_name(self) -> None:
        group = find_contact_group(
            [
                {"name": "QOTD Participants Archive", "resourceName": "contactGroups/1"},
                {"name": "QOTD Participants", "resourceName": "contactGroups/2"},
            ],
            "QOTD Participants",
        )

        self.assertEqual(group["resourceName"], "contactGroups/2")

    def test_extract_contact_email_addresses_normalizes_and_dedupes(self) -> None:
        email_addresses = extract_email_addresses(
            [
                {
                    "person": {
                        "emailAddresses": [
                            {"value": " First@example.com "},
                            {"value": "first@EXAMPLE.com"},
                        ]
                    }
                },
                {"person": {"emailAddresses": [{"value": "second@example.com"}]}},
                {"person": {"names": [{"displayName": "No Email"}]}},
            ]
        )

        self.assertEqual(email_addresses, ["first@example.com", "second@example.com"])

    def test_normalize_email_addresses_ignores_blank_values(self) -> None:
        self.assertEqual(
            normalize_email_addresses([" Person@example.com ", "", "person@example.com"]),
            ["person@example.com"],
        )

    def test_oauth_credentials_use_refresh_token_config(self) -> None:
        credentials = build_oauth_credentials(
            client_id="client-id",
            client_secret="client-secret",
            refresh_token="refresh-token",
        )

        self.assertEqual(credentials.client_id, "client-id")
        self.assertEqual(credentials.client_secret, "client-secret")
        self.assertEqual(credentials.refresh_token, "refresh-token")
        self.assertEqual(credentials.token_uri, GOOGLE_TOKEN_URI)

    def test_dry_run_send_persists_question_record(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "questions.jsonl"

            result = send_question(
                SendQuestionConfig(
                    game_date=date(2026, 7, 9),
                    sender="***SECRET***",
                    contact_group_name="QOTD Participants",
                    state_path=state_path,
                    gmail_user="***SECRET***",
                    oauth_client_id="",
                    oauth_client_secret="",
                    oauth_refresh_token="",
                    participant_emails=("Player@example.com", "player@example.com"),
                    dry_run=True,
                )
            )

            records = read_question_records(state_path)
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["game_date"], "2026-07-09")
            self.assertEqual(records[0]["gmail_message_id"], "dry-run:2026-07-09")
            self.assertEqual(records[0]["correct_option"], "B")
            self.assertIn(result.record.prompt, result.email_body)
            self.assertEqual(result.recipient_count, 1)


if __name__ == "__main__":
    unittest.main()
