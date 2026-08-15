"""Acceptance coverage for Question publication suppression and recovery."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from email.message import EmailMessage

import pytest

from qotd.domain.canonical import OUTBOUND_PENDING, OUTBOUND_SENT, gmail_message_key
from qotd.domain.models import Question
from qotd.external.email.core import ParsedEmailMessage
from qotd.external.storage.memory import InMemoryAdapter
from qotd.usecases.send_question import (
    QUESTION_ALREADY_EXISTS,
    SendQuestionConfig,
    send_question,
)


GAME_DAY = date(2026, 8, 10)
SENDER = "organizer@example.com"
GROUP = "players@example.com"


def _config(
    state: InMemoryAdapter,
    *,
    question_generator=None,
) -> SendQuestionConfig:
    return SendQuestionConfig(
        game_date=GAME_DAY,
        sender=SENDER,
        gmail_user=SENDER,
        oauth_client_id="client",
        oauth_client_secret="secret",
        oauth_refresh_token="token",
        google_group_email=GROUP,
        state_store=state,
        question_generator=question_generator or _generated_question,
    )


def _generated_question(game_day: date, _state: object) -> Question:
    return Question(
        game_date=game_day.isoformat(),
        prompt="Which option is correct?",
        options={"A": "One", "B": "Two", "C": "Three", "D": "Four"},
        correct_option="A",
        source_note="Acceptance source",
        source_url="https://example.com/source",
    )


@pytest.mark.requirements("6.16", "6.18")
def test_manual_question_suppresses_generated_publication() -> None:
    state = InMemoryAdapter()
    generated = False
    sends: list[EmailMessage] = []

    def generate_question(game_day: date, store: object) -> Question:
        nonlocal generated
        generated = True
        return _generated_question(game_day, store)

    def record_send(message: EmailMessage) -> str:
        sends.append(message)
        return "unexpected-send"

    result = send_question(
        _config(state, question_generator=generate_question),
        fetch_messages=lambda _query: [
            ParsedEmailMessage(
                message_id="manual-question",
                thread_id="manual-thread",
                sender_email=SENDER,
                subject="QOTD - 08-10-26",
                sent_at=datetime(2026, 8, 10, 18, tzinfo=UTC),
                body_text="Which option is correct?\nA. One\nB. Two\nC. Three\nD. Four",
            )
        ],
        send_message=record_send,
    )

    game = state.find_game(day=GAME_DAY)
    assert game is not None
    assert game.publication_mode == "manual"
    assert result.skipped_generated_send is True
    assert result.reason == QUESTION_ALREADY_EXISTS
    assert generated is False
    assert sends == []

    intents = tuple(state.outbound_messages.values())
    assert len(intents) == 1
    assert intents[0].status == OUTBOUND_SENT
    assert intents[0].source_message_key == gmail_message_key("manual-question")


@pytest.mark.requirements("6.17")
def test_uncertain_publication_is_reconciled_without_duplicate_delivery() -> None:
    state = InMemoryAdapter()
    config = _config(state)
    sends: list[EmailMessage] = []

    def uncertain_send(message: EmailMessage) -> str:
        sends.append(message)
        raise RuntimeError("delivery outcome unknown")

    with pytest.raises(RuntimeError, match="delivery outcome unknown"):
        send_question(config, fetch_messages=lambda _query: [], send_message=uncertain_send)

    intent = next(iter(state.outbound_messages.values()))
    assert intent.status == OUTBOUND_PENDING

    reconciled_at = intent.created_at + timedelta(minutes=1)

    def duplicate_send(message: EmailMessage) -> str:
        sends.append(message)
        return "duplicate-send"

    result = send_question(
        config,
        fetch_messages=lambda _query: [
            ParsedEmailMessage(
                message_id="delivered-question",
                thread_id="delivery-thread",
                sender_email=SENDER,
                subject=intent.subject,
                sent_at=reconciled_at,
                body_text=intent.body_text,
            )
        ],
        send_message=duplicate_send,
    )

    reconciled = state.find_outbound_message(idempotency_key=intent.idempotency_key)
    assert reconciled is not None
    assert reconciled.status == OUTBOUND_SENT
    assert reconciled.source_message_key == gmail_message_key("delivered-question")
    assert reconciled.sent_at == reconciled_at
    assert result.reason == "publication_intent_already_exists"
    assert len(sends) == 1
