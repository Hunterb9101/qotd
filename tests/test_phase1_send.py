from __future__ import annotations

import unittest
from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import patch

from qotd.cli import build_parser, require_sender_options
from qotd.domain.contacts import normalize_email_addresses
from qotd.domain.dates import question_subject
from qotd.domain.generator import generate_placeholder_question
from qotd.domain.models import CorrectAnswerUpdate, MonthlyScore, ReplyProcessingRecord, StoredQuestion
from qotd.domain.validation import validate_question
from qotd.external.auth.gcp import GOOGLE_TOKEN_URI, build_oauth_credentials
from qotd.external.contacts.google import extract_email_addresses, find_contact_group
from qotd.external.email.core import ParsedEmailMessage
from qotd.presentation.emails import build_participant_email
from qotd.usecases.send_question import (
    QUESTION_ALREADY_EXISTS,
    SendQuestionConfig,
    cody_sent_query,
    detect_cody_sent_question,
    send_question,
)
from tests.support import InMemoryStateStore


class Phase1SendTests(unittest.TestCase):
    def test_sender_setting_supplies_all_email_identities(self) -> None:
        with patch.dict("os.environ", {"QOTD_SENDER": "sender@example.com"}, clear=True):
            parser = build_parser()

        for command in ("send-question", "score-responses", "process-score-adjustments"):
            args = parser.parse_args([command])
            require_sender_options(args)

            self.assertEqual(args.sender, "sender@example.com")
            self.assertEqual(args.gmail_user, "sender@example.com")
            if command == "score-responses":
                self.assertEqual(args.organizer, "sender@example.com")

    def test_question_subject_is_shared_by_participant_email(self) -> None:
        question = generate_placeholder_question("2026-07-09")

        message = build_participant_email(question, "sender@example.com", ["player@example.com"])

        self.assertEqual(question_subject(date(2026, 7, 9)), "QOTD - 2026-07-09")
        self.assertEqual(message["Subject"], question_subject(question.game_date))

    def test_manual_send_query_uses_exact_dated_subject(self) -> None:
        self.assertEqual(
            cody_sent_query(sender="sender@example.com", game_date=date(2026, 7, 9)),
            'in:sent from:sender@example.com subject:"QOTD - 2026-07-09"',
        )

    def test_manual_send_detection_rejects_near_matches_and_wrong_dates(self) -> None:
        messages = [
            self._parsed_message("near", "QOTD - 2026-07-09 extra"),
            self._parsed_message("scoring", "QOTD scoring update - 2026-07-09"),
            self._parsed_message("wrong-date", "QOTD - 2026-07-08"),
        ]

        self.assertIsNone(
            detect_cody_sent_question(
                messages,
                sender="sender@example.com",
                game_date=date(2026, 7, 9),
            )
        )

    def test_exact_manual_send_returns_structured_skip_and_is_rerunnable(self) -> None:
        store = InMemoryStateStore()
        message = self._parsed_message("manual-1", "QOTD - 2026-07-09")
        config = SendQuestionConfig(
            game_date=date(2026, 7, 9),
            sender="sender@example.com",
            contact_group_name="QOTD Participants",
            state_store=store,
            gmail_user="sender@example.com",
            oauth_client_id="",
            oauth_client_secret="",
            oauth_refresh_token="",
        )

        with self.assertLogs("qotd.usecases.send_question", level="INFO") as logs:
            first = send_question(config, fetch_messages=lambda _query: [message])
            second = send_question(config, fetch_messages=lambda _query: [message])

        self.assertEqual(first.outcome, "skipped")
        self.assertEqual(first.reason, QUESTION_ALREADY_EXISTS)
        self.assertEqual(first.subject, "QOTD - 2026-07-09")
        self.assertEqual(first.matched_gmail_message_id, "manual-1")
        self.assertTrue(second.skipped_generated_send)
        self.assertEqual(len(store.read_question_records()), 1)
        self.assertIn("outcome=skipped", logs.output[0])
        self.assertIn("reason=question_subject_already_exists", logs.output[0])
        self.assertIn("gmail_message_id=manual-1", logs.output[0])

    @staticmethod
    def _parsed_message(message_id: str, subject: str) -> ParsedEmailMessage:
        return ParsedEmailMessage(
            message_id=message_id,
            thread_id="thread-1",
            sender_email="sender@example.com",
            subject=subject,
            sent_at=datetime(2026, 7, 9, 18, 0, tzinfo=UTC),
            body_text="Manual question body",
        )

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
            "sender@example.com",
            ["one@example.com", "two@example.com"],
        )
        body = message.get_content()

        self.assertEqual(message["To"], "sender@example.com")
        self.assertEqual(message["Bcc"], "one@example.com, two@example.com")
        self.assertIn(question.prompt, body)
        self.assertIn("A. Mars", body)
        self.assertIn("B. Jupiter", body)
        self.assertIn("D. Neptune", body)
        self.assertNotIn("Correct answer", body)
        self.assertNotIn(question.source_url, body)
        self.assertNotIn(question.source_note, body)

    def test_send_includes_latest_answered_question(self) -> None:
        store = InMemoryStateStore()
        store.append_question_record(
            StoredQuestion(
                game_date="2026-07-10",
                prompt="Friday's question",
                options={"A": "Alpha", "B": "Beta", "C": "Gamma", "D": "Delta"},
                correct_option="",
                source_note="Manual question",
                source_url="",
                source="manual",
                gmail_message_id="friday-message",
                created_at="2026-07-10T18:00:00+00:00",
            )
        )
        store.append_correct_answer_update(
            CorrectAnswerUpdate(
                game_date="2026-07-10",
                correct_option="C",
                source_url="https://example.com/friday-source",
                source_gmail_message_id="answer-message",
                idempotency_key="answer:2026-07-10",
                created_at="2026-07-13T13:00:00+00:00",
            )
        )
        store.append_reply_processing_record(
            ReplyProcessingRecord(
                game_date="2026-07-10",
                email="winner@example.com",
                latest_gmail_message_id="winner-reply",
                points_awarded=1,
                needs_audit=False,
                processed_at="2026-07-13T14:00:00+00:00",
            ),
            interpreted_option="C",
        )
        store.append_reply_processing_record(
            ReplyProcessingRecord(
                game_date="2026-07-10",
                email="other@example.com",
                latest_gmail_message_id="other-reply",
                points_awarded=0,
                needs_audit=False,
                processed_at="2026-07-13T14:00:00+00:00",
            ),
            interpreted_option="A",
        )
        store.append_monthly_score(MonthlyScore(series="0726", email="other@example.com", points=2))
        store.append_monthly_score(MonthlyScore(series="0726", email="winner@example.com", points=4))

        result = send_question(
            SendQuestionConfig(
                game_date=date(2026, 7, 13),
                sender="sender@example.com",
                contact_group_name="QOTD Participants",
                state_store=store,
                gmail_user="sender@example.com",
                oauth_client_id="",
                oauth_client_secret="",
                oauth_refresh_token="",
                participant_emails=("player@example.com",),
                dry_run=True,
            )
        )

        self.assertIn("The correct answer on 2026-07-10 is C. Gamma", result.email_body)
        self.assertIn("Manual question", result.email_body)
        self.assertIn("Points earned:\n- winner@example.com", result.email_body)
        self.assertNotIn("- other@example.com", result.email_body)
        self.assertIn("1. winner@example.com — 4", result.email_body)
        self.assertIn("2. other@example.com — 2", result.email_body)
        self.assertNotIn("friday-source", result.email_body)

    def test_send_skips_newer_incomplete_question_for_latest_answered_recap(self) -> None:
        store = InMemoryStateStore()
        store.append_question_record(
            StoredQuestion(
                game_date="2026-07-08",
                prompt="Completed question",
                options={"A": "Alpha", "B": "Beta", "C": "Gamma", "D": "Delta"},
                correct_option="B",
                source_note="The older complete fun fact",
                source_url="https://example.com/complete",
                source="generated",
                gmail_message_id="completed-message",
                created_at="2026-07-08T18:00:00+00:00",
            )
        )
        store.append_question_record(
            StoredQuestion(
                game_date="2026-07-09",
                prompt="Unresolved question",
                options={"A": "One", "B": "Two", "C": "Three", "D": "Four"},
                correct_option="",
                source_note="Do not show this fact",
                source_url="",
                source="manual",
                gmail_message_id="unresolved-message",
                created_at="2026-07-09T18:00:00+00:00",
            )
        )

        result = send_question(
            SendQuestionConfig(
                game_date=date(2026, 7, 10),
                sender="sender@example.com",
                contact_group_name="QOTD Participants",
                state_store=store,
                gmail_user="sender@example.com",
                oauth_client_id="",
                oauth_client_secret="",
                oauth_refresh_token="",
                participant_emails=("player@example.com",),
                dry_run=True,
            )
        )

        self.assertIn("The correct answer on 2026-07-08 is B. Beta", result.email_body)
        self.assertIn("The older complete fun fact", result.email_body)
        self.assertNotIn("Do not show this fact", result.email_body)

    def test_send_omits_recap_when_previous_answer_is_unresolved(self) -> None:
        store = InMemoryStateStore()
        store.append_question_record(
            StoredQuestion(
                game_date="2026-07-09",
                prompt="Manual question",
                options={},
                correct_option="",
                source_note="Correct answer pending",
                source_url="",
                source="manual",
                gmail_message_id="manual-message",
                created_at="2026-07-09T18:00:00+00:00",
            )
        )

        result = send_question(
            SendQuestionConfig(
                game_date=date(2026, 7, 10),
                sender="sender@example.com",
                contact_group_name="QOTD Participants",
                state_store=store,
                gmail_user="sender@example.com",
                oauth_client_id="",
                oauth_client_secret="",
                oauth_refresh_token="",
                participant_emails=("player@example.com",),
                dry_run=True,
            )
        )

        self.assertNotIn("The correct answer on", result.email_body)

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
                sender="sender@example.com",
                contact_group_name="QOTD Participants",
                state_store=store,
                gmail_user="sender@example.com",
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
