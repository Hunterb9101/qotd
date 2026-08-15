"""Acceptance coverage for an automated daily Game cycle."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from qotd.domain.canonical import GAME_SCORED
from qotd.domain.models import Question
from qotd.domain.scoring import AnswerInterpretation
from qotd.external.email.core import ParsedEmailMessage
from qotd.external.storage.memory import InMemoryAdapter
from qotd.usecases.score_submissions import ScoreResponsesConfig, score_responses
from qotd.usecases.send_question import SendQuestionConfig, send_question
from tests.acceptance.harness.clock import FixedClock


def _question(day: date, prompt: str) -> Question:
    return Question(
        game_date=day.isoformat(),
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


@pytest.mark.requirements(
    "6.2",
    "6.3",
    "6.4",
    "6.5",
    "6.6",
    "6.7",
    "6.12",
    "6.13",
    "6.14",
    "6.15",
    "6.19",
    "6.25",
)
def test_automated_daily_game_cycle_scores_submissions_and_recaps_results() -> None:
    game_day = date(2026, 8, 10)
    scoring_day = date(2026, 8, 11)
    publication_clock = FixedClock(datetime(2026, 8, 10, 18, tzinfo=UTC))
    scoring_clock = FixedClock(datetime(2026, 8, 11, 14, tzinfo=UTC))
    next_publication_clock = FixedClock(datetime(2026, 8, 11, 18, tzinfo=UTC))
    state = InMemoryAdapter(clock=publication_clock)

    publication = send_question(
        _send_config(
            state=state,
            game_day=game_day,
            clock=publication_clock,
            prompt="Which radio call-sign alphabet word represents A?",
        ),
        fetch_messages=lambda _query: [],
    )

    assert publication.recipient_count == 1
    assert "Which radio call-sign alphabet word represents A?" in publication.email_body
    assert all(f"{label}." in publication.email_body for label in "ABCD")
    assert "The Answer" not in publication.email_body

    subject = "QOTD - 08-10-26"
    replies = [
        ParsedEmailMessage(
            "ada-first", "ada-thread", "ada@example.com", subject,
            datetime(2026, 8, 10, 20, tzinfo=UTC), "B",
        ),
        ParsedEmailMessage(
            "ada-latest", "ada-thread", "ada@example.com", f"Re: {subject}",
            datetime(2026, 8, 11, 12, 59, tzinfo=UTC), "The first option, Alpha",
        ),
        ParsedEmailMessage(
            "ben-answer", "ben-thread", "ben@example.com", f"Re: {subject}",
            datetime(2026, 8, 11, 12, 30, tzinfo=UTC), "B",
        ),
        ParsedEmailMessage(
            "grace-late", "grace-thread", "grace@example.com", f"Re: {subject}",
            datetime(2026, 8, 11, 13, 0, tzinfo=UTC), "A",
        ),
        ParsedEmailMessage(
            "lin-review", "lin-thread", "lin@example.com", f"Re: {subject}",
            datetime(2026, 8, 11, 12, 45, tzinfo=UTC), "Either A or B",
        ),
    ]

    def scripted_interpreter(body_text: str) -> AnswerInterpretation:
        if body_text == "The first option, Alpha":
            return AnswerInterpretation(option="A", needs_review=False)
        return AnswerInterpretation(option="UNKNOWN", needs_review=True)

    scoring = score_responses(
        ScoreResponsesConfig(
            scoring_date=scoring_day,
            game_date=game_day,
            sender="organizer@example.com",
            organizer="organizer@example.com",
            gmail_user="organizer@example.com",
            oauth_client_id="client",
            oauth_client_secret="secret",
            oauth_refresh_token="token",
            state_store=state,
            answer_interpreter_factory=lambda _question: scripted_interpreter,
            dry_run=True,
            clock=scoring_clock,
        ),
        fetch_messages=lambda _query: replies,
    )

    game = state.find_game(day=game_day)
    assert game is not None
    assert game.status == GAME_SCORED
    assert game.deadline_at == datetime(2026, 8, 11, 7, tzinfo=game.deadline_at.tzinfo)
    assert {item.ineligibility_reason for item in state.submissions.values()} == {None, "late", "superseded"}
    assert len(state.score_events) == 3
    assert [reply.email for reply in scoring.scoring.correct] == ["ada@example.com"]
    assert [reply.email for reply in scoring.scoring.incorrect] == ["ben@example.com"]
    assert [reply.email for reply in scoring.scoring.needs_review] == ["lin@example.com"]
    assert "Answer: A. Alpha" in scoring.organizer_update_body
    assert "- ada@example.com" in scoring.organizer_update_body
    assert "- ben@example.com: B" in scoring.organizer_update_body
    assert "- lin@example.com: UNKNOWN" in scoring.organizer_update_body
    assert "- grace@example.com: 0" in scoring.organizer_update_body

    following_publication = send_question(
        _send_config(
            state=state,
            game_day=scoring_day,
            clock=next_publication_clock,
            prompt="Which radio call-sign alphabet word represents B?",
        ),
        fetch_messages=lambda _query: [],
    )

    assert "The Answer on 2026-08-10 is A. Alpha" in following_publication.email_body
    assert "Points earned:\n- ada@example.com" in following_publication.email_body
    assert "1. ada@example.com — 1" in following_publication.email_body
    assert "2. ben@example.com — 0" in following_publication.email_body
    assert "3. grace@example.com — 0" in following_publication.email_body
    assert "4. lin@example.com — 0" in following_publication.email_body
    assert "Which radio call-sign alphabet word represents B?" in following_publication.email_body
