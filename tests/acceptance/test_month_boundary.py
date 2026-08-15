"""Acceptance coverage for the monthly Series boundary."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from qotd.domain.models import Question
from qotd.external.email.core import ParsedEmailMessage
from qotd.external.storage.memory import InMemoryAdapter
from qotd.usecases.score_submissions import ScoreResponsesConfig, score_responses
from qotd.usecases.send_question import SendQuestionConfig, send_question
from tests.acceptance.harness.clock import FixedClock


def _question(game_day: date, prompt: str) -> Question:
    return Question(
        game_date=game_day.isoformat(),
        prompt=prompt,
        options={"A": "Alpha", "B": "Bravo", "C": "Charlie", "D": "Delta"},
        correct_option="A",
        source_note="A reliable source confirms Alpha.",
        source_url="https://example.com/alpha",
    )


def _send_config(
    *, state: InMemoryAdapter, game_day: date, clock: FixedClock, prompt: str
) -> SendQuestionConfig:
    return SendQuestionConfig(
        game_date=game_day,
        sender="organizer@example.com",
        gmail_user="organizer@example.com",
        oauth_client_id="client",
        oauth_client_secret="secret",
        oauth_refresh_token="token",
        google_group_email="players@example.com",
        state_store=state,
        question_generator=lambda day, _state: _question(day, prompt),
        dry_run=True,
        clock=clock,
    )


@pytest.mark.requirements("6.20", "6.21", "6.25")
def test_final_weekday_announces_tied_winners_and_starts_next_series() -> None:
    final_august_day = date(2026, 8, 31)
    first_september_day = date(2026, 9, 1)
    august_publication_clock = FixedClock(datetime(2026, 8, 31, 18, tzinfo=UTC))
    september_scoring_clock = FixedClock(datetime(2026, 9, 1, 14, tzinfo=UTC))
    september_publication_clock = FixedClock(datetime(2026, 9, 1, 18, tzinfo=UTC))
    state = InMemoryAdapter(clock=august_publication_clock)

    send_question(
        _send_config(
            state=state,
            game_day=final_august_day,
            clock=august_publication_clock,
            prompt="Which radio call-sign alphabet word represents A?",
        ),
        fetch_messages=lambda _query: [],
    )
    august_game = state.find_game(day=final_august_day)
    assert august_game is not None

    subject = "QOTD - 08-31-26"
    replies = [
        ParsedEmailMessage(
            "ada-answer",
            "ada-thread",
            "ada@example.com",
            f"Re: {subject}",
            datetime(2026, 9, 1, 12, 30, tzinfo=UTC),
            "A",
        ),
        ParsedEmailMessage(
            "ben-answer",
            "ben-thread",
            "ben@example.com",
            f"Re: {subject}",
            datetime(2026, 9, 1, 12, 45, tzinfo=UTC),
            "A",
        ),
        ParsedEmailMessage(
            "cara-answer",
            "cara-thread",
            "cara@example.com",
            f"Re: {subject}",
            datetime(2026, 9, 1, 12, 50, tzinfo=UTC),
            "B",
        ),
    ]
    score_responses(
        ScoreResponsesConfig(
            scoring_date=first_september_day,
            game_date=final_august_day,
            sender="organizer@example.com",
            organizer="organizer@example.com",
            gmail_user="organizer@example.com",
            oauth_client_id="client",
            oauth_client_secret="secret",
            oauth_refresh_token="token",
            state_store=state,
            dry_run=True,
            clock=september_scoring_clock,
        ),
        fetch_messages=lambda _query: replies,
    )

    august_scores = state.read_scoreboard(series_id=august_game.series_id)
    assert [(entry.email, entry.score) for entry in august_scores] == [
        ("ada@example.com", 1),
        ("ben@example.com", 1),
        ("cara@example.com", 0),
    ]

    september_publication = send_question(
        _send_config(
            state=state,
            game_day=first_september_day,
            clock=september_publication_clock,
            prompt="Which radio call-sign alphabet word represents B?",
        ),
        fetch_messages=lambda _query: [],
    )

    assert "Final Scoreboard for 2026-08:" in september_publication.email_body
    assert "- ada@example.com with 1 points" in september_publication.email_body
    assert "- ben@example.com with 1 points" in september_publication.email_body
    assert "cara@example.com with 0 points" not in september_publication.email_body
    assert "A new Series starts today with a zeroed Scoreboard." in september_publication.email_body

    september_game = state.find_game(day=first_september_day)
    assert september_game is not None
    assert september_game.series_id != august_game.series_id
    assert state.read_scoreboard(series_id=september_game.series_id) == ()
