from __future__ import annotations

from datetime import date
from email.message import EmailMessage

import pytest

from qotd.domain.canonical import OutboundMessage
from qotd.domain.models import Question
from qotd.usecases.send_question import SendQuestionConfig, send_question
from qotd.external.storage.memory import InMemoryAdapter


def test_production_send_requires_google_group_address() -> None:
    """Fail closed instead of reverting to multi-recipient Bcc delivery."""

    with pytest.raises(RuntimeError, match="Google Group email"):
        send_question(
            SendQuestionConfig(
                game_date=date(2026, 7, 9),
                sender="sender@example.com",
                state_store=InMemoryAdapter(),
                gmail_user="sender@example.com",
                oauth_client_id="",
                oauth_client_secret="",
                oauth_refresh_token="",
            ),
            fetch_messages=lambda _query: [],
        )


def test_canonical_send_publishes_a_game_without_snapshot_state() -> None:
    """Canonical publication requires no legacy monthly-score snapshots."""

    store = InMemoryAdapter()
    first_november_game = date(2026, 11, 2)

    monday_send = send_question(
        SendQuestionConfig(
            game_date=first_november_game,
            sender="sender@example.com",
            gmail_user="sender@example.com",
            oauth_client_id="client-id",
            oauth_client_secret="client-secret",
            oauth_refresh_token="refresh-token",
            state_store=store,
            google_group_email="qotd-group@googlegroups.com",
            question_generator=lambda game_date, _store: Question(
                game_date=game_date.isoformat(),
                prompt="What is the first letter of the alphabet?",
                options={"A": "A", "B": "B", "C": "C", "D": "D"},
                correct_option="A",
                source_note="The alphabet starts with A.",
                source_url="https://example.com/alphabet",
            ),
            dry_run=True,
        ),
        fetch_messages=lambda _query: [],
    )

    assert monday_send.record.game_date == first_november_game.isoformat()
    assert store.find_game(day=first_november_game).status == "published"  # type: ignore[union-attr]


def test_delivered_group_question_retains_reply_to_sender() -> None:
    """The committed Group delivery intent must preserve the rendered reply route."""

    sent: list[EmailMessage] = []

    def send_message(message: EmailMessage) -> str:
        sent.append(message)
        return "gmail-question-1"

    send_question(
        SendQuestionConfig(
            game_date=date(2026, 8, 10),
            sender="sender@example.com",
            gmail_user="sender@example.com",
            oauth_client_id="client-id",
            oauth_client_secret="client-secret",
            oauth_refresh_token="refresh-token",
            state_store=InMemoryAdapter(),
            google_group_email="qotd-group@googlegroups.com",
            question_generator=lambda game_date, _store: Question(
                game_date=game_date.isoformat(), prompt="Question?",
                options={"A": "A", "B": "B", "C": "C", "D": "D"},
                correct_option="A", source_note="Source", source_url="https://example.com/source",
            ),
        ),
        fetch_messages=lambda _query: [],
        send_message=send_message,
    )

    assert len(sent) == 1
    assert sent[0]["Reply-To"] == "sender@example.com"


def test_publication_loser_does_not_send_another_question() -> None:
    """Only the run whose intent is persisted is allowed to deliver it."""

    class CompetingPublicationAdapter(InMemoryAdapter):
        def replace_pending_game(self, game, *, series=None, outbound_message=None):  # type: ignore[no-untyped-def]
            assert outbound_message is not None
            competing_intent = OutboundMessage(
                id="competing-intent",
                idempotency_key=outbound_message.idempotency_key,
                message_type=outbound_message.message_type,
                recipient=outbound_message.recipient,
                subject=outbound_message.subject,
                body_text=outbound_message.body_text,
                status=outbound_message.status,
                created_at=outbound_message.created_at,
                game_id=outbound_message.game_id,
            )
            return super().replace_pending_game(game, series=series, outbound_message=competing_intent)

    sent: list[EmailMessage] = []
    result = send_question(
        SendQuestionConfig(
            game_date=date(2026, 8, 10),
            sender="sender@example.com",
            gmail_user="sender@example.com",
            oauth_client_id="client-id",
            oauth_client_secret="client-secret",
            oauth_refresh_token="refresh-token",
            state_store=CompetingPublicationAdapter(),
            google_group_email="qotd-group@googlegroups.com",
            question_generator=lambda game_date, _store: Question(
                game_date=game_date.isoformat(), prompt="Question?",
                options={"A": "A", "B": "B", "C": "C", "D": "D"},
                correct_option="A", source_note="Source", source_url="https://example.com/source",
            ),
        ),
        fetch_messages=lambda _query: [],
        send_message=lambda message: sent.append(message) or "unexpected-send",
    )

    assert result.reason == "publication_intent_already_exists"
    assert sent == []
