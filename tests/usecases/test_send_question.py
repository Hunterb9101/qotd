from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from qotd.domain.models import Question, StoredQuestion
from qotd.external.email.core import ParsedEmailMessage
from qotd.usecases.score_responses import ScoreResponsesConfig, score_responses
from qotd.usecases.send_question import SendQuestionConfig, send_question
from tests.support import InMemoryStateStore


def _question(game_date: date) -> StoredQuestion:
    return StoredQuestion(
        game_date=game_date.isoformat(),
        prompt="Which planet has the Great Red Spot?",
        options={"A": "Mars", "B": "Jupiter", "C": "Saturn", "D": "Neptune"},
        correct_option="B",
        source_note="Jupiter has the Great Red Spot.",
        source_url="https://example.com/jupiter",
        source="generated",
        gmail_message_id=f"question:{game_date.isoformat()}",
        created_at=datetime.combine(game_date, datetime.min.time(), tzinfo=UTC)
        .replace(hour=18)
        .isoformat(),
    )


def _reply(game_date: date, email: str, answer: str) -> ParsedEmailMessage:
    return ParsedEmailMessage(
        message_id=f"reply:{game_date.isoformat()}:{email}",
        thread_id=f"thread:{game_date.isoformat()}",
        sender_email=email,
        subject=f"Re: QOTD - {game_date:%m-%d-%y}",
        sent_at=datetime.combine(game_date, datetime.min.time(), tzinfo=UTC).replace(hour=19),
        body_text=answer,
    )


def _score_config(
    store: InMemoryStateStore,
    *,
    game_date: date,
    scoring_date: date,
) -> ScoreResponsesConfig:
    return ScoreResponsesConfig(
        scoring_date=scoring_date,
        game_date=game_date,
        sender="sender@example.com",
        organizer="organizer@example.com",
        gmail_user="sender@example.com",
        oauth_client_id="client-id",
        oauth_client_secret="client-secret",
        oauth_refresh_token="refresh-token",
        state_store=store,
        dry_run=True,
    )


def test_production_send_requires_google_group_address() -> None:
    """Fail closed instead of reverting to multi-recipient Bcc delivery."""

    with pytest.raises(RuntimeError, match="Google Group email"):
        send_question(
            SendQuestionConfig(
                game_date=date(2026, 7, 9),
                sender="sender@example.com",
                state_store=InMemoryStateStore(),
                gmail_user="sender@example.com",
                oauth_client_id="",
                oauth_client_secret="",
                oauth_refresh_token="",
            ),
            fetch_messages=lambda _query: [],
        )


def test_friday_month_end_announces_all_winners_on_monday_and_starts_clean_scores() -> None:
    """Carry a Friday month end across the weekend without carrying its scores."""

    store = InMemoryStateStore()
    final_october_game = date(2026, 10, 30)
    first_november_game = date(2026, 11, 2)
    store.append_question_record(_question(final_october_game))

    october_result = score_responses(
        _score_config(
            store,
            game_date=final_october_game,
            scoring_date=first_november_game,
        ),
        fetch_messages=lambda _query: [
            _reply(final_october_game, "ada@example.com", "B"),
            _reply(final_october_game, "grace@example.com", "B"),
            _reply(final_october_game, "linus@example.com", "A"),
        ],
    )

    assert "Monthly winner announcement:" in october_result.organizer_update_body
    assert "ada@example.com with 1 points" in october_result.organizer_update_body
    assert "grace@example.com with 1 points" in october_result.organizer_update_body

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

    assert "Monthly winners:" in monday_send.email_body
    assert "ada@example.com with 1 points" in monday_send.email_body
    assert "grace@example.com with 1 points" in monday_send.email_body
    assert "A new monthly competition starts today with clean standings." in monday_send.email_body
    assert "Current standings:" not in monday_send.email_body

    november_result = score_responses(
        _score_config(
            store,
            game_date=first_november_game,
            scoring_date=date(2026, 11, 3),
        ),
        fetch_messages=lambda _query: [
            _reply(first_november_game, "linus@example.com", "A"),
        ],
    )

    assert [(score.email, score.points) for score in november_result.scoring.standings] == [
        ("linus@example.com", 1)
    ]
    assert store.read_monthly_scores(series="1026") == [
        {"series": "1026", "email": "ada@example.com", "points": 1},
        {"series": "1026", "email": "grace@example.com", "points": 1},
    ]
    assert store.read_monthly_scores(series="1126") == [
        {"series": "1126", "email": "linus@example.com", "points": 1}
    ]
