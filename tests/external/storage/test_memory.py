"""Behavior of the source-backed in-memory canonical-state adapter."""

from dataclasses import replace
from datetime import UTC, date, datetime

import pytest

from qotd.domain.canonical import GAME_PENDING, Game, ScoreEvent, ScoreboardEntry, Submission, new_id
from qotd.external.storage.memory import InMemoryAdapter


def test_canonical_state_normalizes_players_and_derives_scoreboard_from_events() -> None:
    state = InMemoryAdapter()
    series = state.create_or_find_series(
        name="August 2026", starts_on=date(2026, 8, 1), ends_on=date(2026, 8, 31)
    )
    player = state.create_or_find_player(email="Ada@Example.com ")
    game = state.publish_game(
        Game(
            id=new_id(), series_id=series.id, day=date(2026, 8, 10), status=GAME_PENDING,
            publication_mode="manual", deadline_at=datetime(2026, 8, 11, tzinfo=UTC),
            created_at=datetime(2026, 8, 10, tzinfo=UTC), updated_at=datetime(2026, 8, 10, tzinfo=UTC),
        )
    )
    state.record_submission(
        Submission(
            id=new_id(), source_message_key="submission-1", game_id=game.id, player_id=player.id,
            body_text="A", received_at=datetime(2026, 8, 10, tzinfo=UTC), is_eligible=True,
            created_at=datetime(2026, 8, 10, tzinfo=UTC), updated_at=datetime(2026, 8, 10, tzinfo=UTC),
        )
    )
    state.record_manual_score_event(
        ScoreEvent(new_id(), "manual-1", player.id, series.id, "manual", 2, datetime(2026, 8, 10, tzinfo=UTC))
    )

    assert state.read_scoreboard(series_id=series.id)[0].email == "ada@example.com"
    assert state.read_scoreboard(series_id=series.id)[0].score == 2


def test_canonical_state_retains_late_and_superseded_submissions() -> None:
    state = InMemoryAdapter()
    series = state.create_or_find_series(
        name="August 2026", starts_on=date(2026, 8, 1), ends_on=date(2026, 8, 31)
    )
    player = state.create_or_find_player(email="ada@example.com")
    game = state.publish_game(
        Game(
            id=new_id(), series_id=series.id, day=date(2026, 8, 10), status=GAME_PENDING,
            publication_mode="manual", deadline_at=datetime(2026, 8, 11, tzinfo=UTC),
            created_at=datetime(2026, 8, 10, tzinfo=UTC), updated_at=datetime(2026, 8, 10, tzinfo=UTC),
        )
    )
    first = state.record_submission(
        Submission(new_id(), "first", game.id, player.id, "A", datetime(2026, 8, 10, tzinfo=UTC), True,
                   datetime(2026, 8, 10, tzinfo=UTC), datetime(2026, 8, 10, tzinfo=UTC))
    )
    second = state.record_submission(
        Submission(new_id(), "second", game.id, player.id, "B", datetime(2026, 8, 10, 1, tzinfo=UTC), True,
                   datetime(2026, 8, 10, tzinfo=UTC), datetime(2026, 8, 10, tzinfo=UTC))
    )
    late = state.record_submission(
        Submission(new_id(), "late", game.id, player.id, "C", datetime(2026, 8, 11, tzinfo=UTC), True,
                   datetime(2026, 8, 11, tzinfo=UTC), datetime(2026, 8, 11, tzinfo=UTC))
    )

    assert state.submissions[first.id].ineligibility_reason == "superseded"
    assert second.is_eligible
    assert late.ineligibility_reason == "late"


def test_manual_score_event_adds_a_new_player_to_the_scoreboard() -> None:
    state = InMemoryAdapter()
    series = state.create_or_find_series(
        name="August 2026", starts_on=date(2026, 8, 1), ends_on=date(2026, 8, 31)
    )
    player = state.create_or_find_player(email="new@example.com")
    state.record_manual_score_event(
        ScoreEvent(
            new_id(), "manual-new-player", player.id, series.id, "manual", 3,
            datetime(2026, 8, 10, tzinfo=UTC), reason="organizer correction",
        )
    )

    assert state.read_scoreboard(series_id=series.id) == (
        ScoreboardEntry(series.id, player.id, "new@example.com", 3),
    )


def test_pending_answer_is_attached_when_the_manual_game_is_published() -> None:
    state = InMemoryAdapter()
    series = state.create_or_find_series(
        name="August 2026", starts_on=date(2026, 8, 1), ends_on=date(2026, 8, 31)
    )
    now = datetime(2026, 8, 10, tzinfo=UTC)
    pending = state.set_answer(
        Game(
            new_id(), series.id, date(2026, 8, 10), GAME_PENDING, "manual", now, now, now,
            correct_option="B", answer_source_url="https://example.com/source",
        )
    )

    published = state.publish_game(
        Game(
            new_id(), series.id, date(2026, 8, 10), GAME_PENDING, "manual", now, now, now,
            question_prompt="Which option is correct?", question_options={"A": "No", "B": "Yes"},
        )
    )

    assert published.id == pending.id
    assert published.status == "published"
    assert published.correct_option == "B"


def test_distinct_second_answer_is_rejected() -> None:
    state = InMemoryAdapter()
    series = state.create_or_find_series(
        name="August 2026", starts_on=date(2026, 8, 1), ends_on=date(2026, 8, 31)
    )
    now = datetime(2026, 8, 10, tzinfo=UTC)
    game = state.set_answer(
        Game(new_id(), series.id, date(2026, 8, 10), GAME_PENDING, "manual", now, now, now, correct_option="A")
    )

    with pytest.raises(ValueError, match="conflicts"):
        state.set_answer(replace(game, correct_option="B"))
