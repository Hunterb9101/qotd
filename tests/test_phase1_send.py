from __future__ import annotations

import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from qotd.domain.contacts import normalize_email_addresses
from qotd.domain.generator import generate_placeholder_question
from qotd.domain.validation import validate_question
from qotd.external.auth.gcp import GOOGLE_TOKEN_URI, build_oauth_credentials
from qotd.external.contacts.google import extract_email_addresses, find_contact_group
from qotd.presentation.emails import build_participant_email
from qotd.usecases.send_question import SendQuestionConfig, send_question
from tests.support import InMemoryStateStore


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
        class FakeCredentials:
            def __init__(self, **kwargs: object) -> None:
                self.client_id = kwargs["client_id"]
                self.client_secret = kwargs["client_secret"]
                self.refresh_token = kwargs["refresh_token"]
                self.token_uri = kwargs["token_uri"]

        fake_module = SimpleNamespace(Credentials=FakeCredentials)
        with patch("qotd.external.auth.gcp.importlib.import_module", return_value=fake_module):
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
        store = InMemoryStateStore()

        result = send_question(
            SendQuestionConfig(
                game_date=date(2026, 7, 9),
                sender="***SECRET***",
                contact_group_name="QOTD Participants",
                state_store=store,
                gmail_user="***SECRET***",
                oauth_client_id="",
                oauth_client_secret="",
                oauth_refresh_token="",
                participant_emails=("Player@example.com", "player@example.com"),
                dry_run=True,
            )
        )

        records = store.read_question_records()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["game_date"], "2026-07-09")
        self.assertEqual(records[0]["gmail_message_id"], "dry-run:2026-07-09")
        self.assertEqual(records[0]["correct_option"], "B")
        self.assertIn(result.record.prompt, result.email_body)
        self.assertEqual(result.recipient_count, 1)


if __name__ == "__main__":
    unittest.main()
