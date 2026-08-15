from datetime import UTC, date, datetime, timedelta
from dataclasses import replace
from email.message import EmailMessage

import pytest

from qotd.domain.canonical import GAME_PENDING, GAME_SCORED, INSTRUCTION_APPLIED, OUTBOUND_PENDING, OUTBOUND_SENT, Game, OrganizerInstruction, ScoreEvent, Submission, gmail_message_key, new_id
from qotd.domain.models import Question
from qotd.external.email.core import ParsedEmailMessage
from qotd.usecases.handle_answer import apply_answer_instruction
from qotd.usecases.transition_game import ScoreGameTransition, score_game_transition
from qotd.usecases.publish_game import publish_manual_game
from qotd.usecases.get_question_history import MissingQuestionError
from qotd.usecases.score_submissions import ScoreResponsesConfig, score_responses
from qotd.usecases.record_score_event import ManualScoreEventRequest, record_score_event
from qotd.usecases.adjust_score import (
    ManualScoreEventConfig,
    ProcessManualScoreEventEmailsConfig,
    process_manual_score_event_emails,
    record_manual_score_event,
)
from qotd.usecases.send_question import SendQuestionConfig, send_question
from qotd.external.storage.memory import InMemoryAdapter


def test_transition_game_writes_events_and_marks_the_published_game_scored() -> None:
    state = InMemoryAdapter()
    now = datetime(2026, 8, 11, tzinfo=UTC)
    series = state.create_or_find_series(name="August 2026", starts_on=date(2026, 8, 1), ends_on=date(2026, 8, 31))
    player = state.create_or_find_player(email="ada@example.com")
    game = state.publish_game(
        Game(new_id(), series.id, date(2026, 8, 10), GAME_PENDING, "manual", now, now, now, correct_option="A")
    )
    submission = state.record_submission(
        Submission(new_id(), "submission", game.id, player.id, "A", game.deadline_at - timedelta(minutes=1), True, now, now)
    )
    scored = score_game_transition(
        state=state,
        transition=ScoreGameTransition(
            game=replace(game, scored_at=now),
            score_events=(
                ScoreEvent(
                    new_id(), "automatic-event", player.id, series.id, "automatic", 1, now,
                    game_id=game.id, submission_id=submission.id,
                ),
            ),
        ),
    )

    assert scored.status == GAME_SCORED
    assert state.read_scoreboard(series_id=series.id)[0].score == 1


def test_failed_scoring_transition_persists_neither_events_nor_scored_game() -> None:
    state = InMemoryAdapter()
    now = datetime(2026, 8, 11, tzinfo=UTC)
    series = state.create_or_find_series(name="August", starts_on=date(2026, 8, 1), ends_on=date(2026, 8, 31))
    game = Game(new_id(), series.id, date(2026, 8, 10), GAME_PENDING, "manual", now, now, now, correct_option="A")
    state.games[game.id] = game
    player = state.create_or_find_player(email="ada@example.com")

    with pytest.raises(ValueError, match="published"):
        score_game_transition(
            state=state,
            transition=ScoreGameTransition(
                game=replace(game, scored_at=now),
                score_events=(ScoreEvent(new_id(), "event", player.id, series.id, "automatic", 1, now, game_id=game.id),),
            ),
        )

    assert state.find_game(day=game.day).status == GAME_PENDING  # type: ignore[union-attr]
    assert state.score_events == {}


def test_scoring_rejects_an_automatic_event_without_an_eligible_submission() -> None:
    state = InMemoryAdapter()
    now = datetime(2026, 8, 11, tzinfo=UTC)
    series = state.create_or_find_series(name="August", starts_on=date(2026, 8, 1), ends_on=date(2026, 8, 31))
    game = state.publish_game(
        Game(new_id(), series.id, date(2026, 8, 10), GAME_PENDING, "manual", now, now, now, correct_option="A")
    )
    player = state.create_or_find_player(email="ada@example.com")

    with pytest.raises(ValueError, match="selected eligible"):
        score_game_transition(
            state=state,
            transition=ScoreGameTransition(
                game=replace(game, scored_at=now),
                score_events=(ScoreEvent(new_id(), "invalid", player.id, series.id, "automatic", 1, now, game_id=game.id),),
            ),
        )

    assert state.find_game(day=game.day).status != GAME_SCORED  # type: ignore[union-attr]
    assert state.score_events == {}


def test_manual_score_event_for_a_new_player_appears_in_the_scoreboard() -> None:
    state = InMemoryAdapter()
    now = datetime(2026, 8, 11, tzinfo=UTC)
    series = state.create_or_find_series(name="August 2026", starts_on=date(2026, 8, 1), ends_on=date(2026, 8, 31))
    event = record_score_event(
        state=state,
        created_at=now,
        request=ManualScoreEventRequest(
            player_email="new@example.com", points_delta=-1, reason="correction", series_id=series.id,
            organizer_instruction=OrganizerInstruction(
                new_id(), gmail_message_key("manual-event"), "organizer@example.com", "Correction", now,
                "record-score-event", INSTRUCTION_APPLIED, now,
            ),
        ),
    )

    assert event.points_delta == -1
    assert state.read_scoreboard(series_id=series.id)[0].email == "new@example.com"


def test_manual_score_event_uses_a_canonical_score_event() -> None:
    state = InMemoryAdapter()
    game_day = date(2026, 8, 10)
    state.publish_game(
        Game(new_id(), state.create_or_find_series(name="August", starts_on=date(2026, 8, 1), ends_on=date(2026, 8, 31)).id,
             game_day, GAME_PENDING, "manual", datetime(2026, 8, 11, tzinfo=UTC), datetime(2026, 8, 11, tzinfo=UTC),
             datetime(2026, 8, 11, tzinfo=UTC), correct_option="A")
    )
    result = record_manual_score_event(
        ManualScoreEventConfig(email="new@example.com", points_delta=2, reason="correction", state_store=state, game_date=game_day)
    )

    assert result.player_score.points == 2
    assert next(iter(state.score_events.values())).event_type == "manual"


def test_series_wide_manual_score_event_does_not_require_a_game() -> None:
    state = InMemoryAdapter()

    result = record_manual_score_event(
        ManualScoreEventConfig(email="new@example.com", points_delta=-2, reason="correction", state_store=state, series="0826")
    )

    assert result.applied
    assert result.player_score.points == -2
    assert next(iter(state.score_events.values())).game_id is None


def test_malformed_manual_score_event_email_is_durably_rejected() -> None:
    state = InMemoryAdapter()
    result = process_manual_score_event_emails(
        ProcessManualScoreEventEmailsConfig(
            sender="sender@example.com", gmail_user="sender@example.com", organizer_emails=("organizer@example.com",),
            oauth_client_id="client", oauth_client_secret="secret", oauth_refresh_token="token", state_store=state,
        ),
        fetch_messages=lambda _query: [
            ParsedEmailMessage("instruction", "thread", "organizer@example.com", "Correction", datetime(2026, 8, 11, tzinfo=UTC), "Action: record-score-event\nPlayer: ada@example.com\nDay: 2026-08-10\nPoints: nope\nReason: correction")
        ],
        send_message=lambda _message: "response",
        mark_message_handled=lambda _message_id: None,
    )

    assert result.processed[0].status == "Points must be an integer"
    assert next(iter(state.instructions.values())).status == "rejected"


def test_manual_score_event_ignores_a_player_submission() -> None:
    state = InMemoryAdapter()
    sent: list[EmailMessage] = []
    handled: list[str] = []
    submission = ParsedEmailMessage(
        "submission", "thread", "player@example.com", "Re: QOTD", datetime(2026, 8, 11, tzinfo=UTC), "A"
    )

    result = process_manual_score_event_emails(
        ProcessManualScoreEventEmailsConfig(
            sender="sender@example.com", gmail_user="sender@example.com", organizer_emails=("organizer@example.com",),
            oauth_client_id="client", oauth_client_secret="secret", oauth_refresh_token="token", state_store=state,
        ),
        fetch_messages=lambda _query: [submission],
        send_message=lambda message: sent.append(message) or "response",
        mark_message_handled=handled.append,
    )

    assert result.processed == ()
    assert state.instructions == state.outbound_messages == {}
    assert sent == []
    assert handled == []


def test_manual_score_event_commits_instruction_event_and_outcome_before_delivery() -> None:
    state = InMemoryAdapter()
    series = state.create_or_find_series(name="August", starts_on=date(2026, 8, 1), ends_on=date(2026, 8, 31))
    game_day = date(2026, 8, 10)
    state.publish_game(Game(new_id(), series.id, game_day, GAME_PENDING, "manual", datetime(2026, 8, 11, tzinfo=UTC), datetime(2026, 8, 11, tzinfo=UTC), datetime(2026, 8, 11, tzinfo=UTC), correct_option="A"))
    message = ParsedEmailMessage("instruction", "thread", "organizer@example.com", "Correction", datetime(2026, 8, 11, tzinfo=UTC), "Action: record-score-event\nPlayer: ada@example.com\nDay: 2026-08-10\nPoints: 2\nReason: correction")

    handled: list[str] = []

    def send(outgoing: EmailMessage) -> str:
        assert len(state.instructions) == len(state.score_events) == len(state.outbound_messages) == 1
        assert outgoing["To"] == "organizer@example.com"
        return "outcome"

    result = process_manual_score_event_emails(
        ProcessManualScoreEventEmailsConfig(sender="sender@example.com", gmail_user="sender@example.com", organizer_emails=("organizer@example.com",), oauth_client_id="client", oauth_client_secret="secret", oauth_refresh_token="token", state_store=state),
        fetch_messages=lambda _query: [message], send_message=send, mark_message_handled=handled.append,
    )

    assert result.processed[0].status == "applied"
    assert next(iter(state.outbound_messages.values())).status == OUTBOUND_SENT
    assert handled == ["instruction"]


def test_duplicate_manual_score_event_reuses_its_committed_outcome_intent() -> None:
    state = InMemoryAdapter()
    series = state.create_or_find_series(name="August", starts_on=date(2026, 8, 1), ends_on=date(2026, 8, 31))
    game_day = date(2026, 8, 10)
    state.publish_game(Game(new_id(), series.id, game_day, GAME_PENDING, "manual", datetime(2026, 8, 11, tzinfo=UTC), datetime(2026, 8, 11, tzinfo=UTC), datetime(2026, 8, 11, tzinfo=UTC), correct_option="A"))
    message = ParsedEmailMessage("instruction", "thread", "organizer@example.com", "Correction", datetime(2026, 8, 11, tzinfo=UTC), "Action: record-score-event\nPlayer: ada@example.com\nDay: 2026-08-10\nPoints: 2\nReason: correction")
    config = ProcessManualScoreEventEmailsConfig(sender="sender@example.com", gmail_user="sender@example.com", organizer_emails=("organizer@example.com",), oauth_client_id="client", oauth_client_secret="secret", oauth_refresh_token="token", state_store=state)
    sent: list[EmailMessage] = []

    def send(outgoing: EmailMessage) -> str:
        sent.append(outgoing)
        return "outcome"

    process_manual_score_event_emails(
        config, fetch_messages=lambda _query: [message], send_message=send, mark_message_handled=lambda _message_id: None
    )
    duplicate = process_manual_score_event_emails(
        config, fetch_messages=lambda _query: [message], send_message=send, mark_message_handled=lambda _message_id: None
    )

    assert duplicate.processed[0].status == "skipped_duplicate"
    assert len(state.score_events) == len(state.outbound_messages) == len(sent) == 1


def test_scoring_reports_a_missing_game_with_a_dedicated_error() -> None:
    with pytest.raises(MissingQuestionError, match="2026-08-07"):
        score_responses(
            ScoreResponsesConfig(
                scoring_date=date(2026, 8, 10),
                game_date=date(2026, 8, 7),
                sender="organizer@example.com",
                organizer="organizer@example.com",
                gmail_user="organizer@example.com",
                oauth_client_id="client",
                oauth_client_secret="secret",
                oauth_refresh_token="token",
                state_store=InMemoryAdapter(),
                dry_run=True,
            )
        )


def test_scoring_retains_late_and_superseded_submissions_but_events_link_only_selected_submission() -> None:
    state = InMemoryAdapter()
    game_day = date(2026, 8, 10)
    game = publish_manual_game(
        state=state,
        game_day=game_day,
        question=Question(
            game_date=game_day.isoformat(), prompt="Question?", options={"A": "One", "B": "Two", "C": "Three", "D": "Four"},
            correct_option="", source_note="", source_url="", source="manual",
        ),
        message_id="question", published_at=datetime(2026, 8, 10, tzinfo=UTC),
    )
    state.set_answer(replace(game, correct_option="A", answer_source_url="https://example.com"))
    result = score_responses(
        ScoreResponsesConfig(
            scoring_date=date(2026, 8, 11), game_date=game_day, sender="organizer@example.com",
            organizer="organizer@example.com", gmail_user="organizer@example.com", oauth_client_id="client",
            oauth_client_secret="secret", oauth_refresh_token="token", state_store=state, dry_run=True,
        ),
        fetch_messages=lambda _query: [
            ParsedEmailMessage("first", "thread", "ada@example.com", "QOTD - 08-10-26", datetime(2026, 8, 10, 18, tzinfo=UTC), "B"),
            ParsedEmailMessage("latest", "thread", "ada@example.com", "Re: QOTD - 08-10-26", datetime(2026, 8, 11, 1, tzinfo=UTC), "A"),
            ParsedEmailMessage("late", "thread", "grace@example.com", "QOTD - 08-10-26", datetime(2026, 8, 11, 13, tzinfo=UTC), "A"),
        ],
    )

    submissions = tuple(state.submissions.values())
    assert {submission.ineligibility_reason for submission in submissions} == {None, "superseded", "late"}
    assert len(state.score_events) == 1
    event = next(iter(state.score_events.values()))
    assert state.submissions[event.submission_id].body_text == "A"  # type: ignore[index]
    assert result.scoring.correct[0].email == "ada@example.com"


def test_out_of_order_submission_collection_keeps_the_latest_reply_eligible() -> None:
    state = InMemoryAdapter()
    now = datetime(2026, 8, 11, tzinfo=UTC)
    series = state.create_or_find_series(name="August", starts_on=date(2026, 8, 1), ends_on=date(2026, 8, 31))
    game = state.publish_game(
        Game(new_id(), series.id, date(2026, 8, 10), GAME_PENDING, "manual", now, now, now, correct_option="A")
    )
    player = state.create_or_find_player(email="ada@example.com")
    later = state.record_submission(
        Submission(new_id(), "later", game.id, player.id, "A", game.deadline_at - timedelta(hours=1), True, now, now)
    )
    earlier = state.record_submission(
        Submission(new_id(), "earlier", game.id, player.id, "B", game.deadline_at - timedelta(hours=2), True, now, now)
    )

    assert state.submissions[later.id].is_eligible
    assert state.submissions[earlier.id].ineligibility_reason == "superseded"


def test_same_time_submissions_use_source_message_key_as_a_stable_tie_breaker() -> None:
    state = InMemoryAdapter()
    now = datetime(2026, 8, 11, tzinfo=UTC)
    series = state.create_or_find_series(name="August", starts_on=date(2026, 8, 1), ends_on=date(2026, 8, 31))
    game = state.publish_game(
        Game(new_id(), series.id, date(2026, 8, 10), GAME_PENDING, "manual", now, now, now, correct_option="A")
    )
    player = state.create_or_find_player(email="ada@example.com")
    received_at = game.deadline_at - timedelta(hours=1)
    first = state.record_submission(Submission(new_id(), "a", game.id, player.id, "A", received_at, True, now, now))
    second = state.record_submission(Submission(new_id(), "b", game.id, player.id, "B", received_at, True, now, now))

    assert state.submissions[first.id].ineligibility_reason == "superseded"
    assert state.submissions[second.id].is_eligible


def test_scoring_a_game_twice_does_not_duplicate_automatic_score_events() -> None:
    state = InMemoryAdapter()
    game_day = date(2026, 8, 10)
    game = publish_manual_game(
        state=state, game_day=game_day,
        question=Question(game_date=game_day.isoformat(), prompt="Question?", options={"A": "One", "B": "Two", "C": "Three", "D": "Four"}, correct_option="", source_note="", source_url="", source="manual"),
        message_id="question", published_at=datetime(2026, 8, 10, tzinfo=UTC),
    )
    state.set_answer(replace(game, correct_option="A", answer_source_url="https://example.com"))
    reply = ParsedEmailMessage("reply", "thread", "ada@example.com", "QOTD - 08-10-26", datetime(2026, 8, 10, 18, tzinfo=UTC), "A")
    config = ScoreResponsesConfig(
        scoring_date=date(2026, 8, 11), game_date=game_day, sender="organizer@example.com", organizer="organizer@example.com",
        gmail_user="organizer@example.com", oauth_client_id="client", oauth_client_secret="secret", oauth_refresh_token="token",
        state_store=state, dry_run=True,
    )

    score_responses(config, fetch_messages=lambda _query: [reply])
    score_responses(config, fetch_messages=lambda _query: [reply])

    assert len(state.score_events) == 1


def test_successful_scoring_commits_one_pending_organizer_update_intent() -> None:
    state = InMemoryAdapter()
    game_day = date(2026, 8, 10)
    game = publish_manual_game(
        state=state, game_day=game_day,
        question=Question(game_date=game_day.isoformat(), prompt="Question?", options={"A": "One", "B": "Two", "C": "Three", "D": "Four"}, correct_option="", source_note="", source_url="", source="manual"),
        message_id="question", published_at=datetime(2026, 8, 10, tzinfo=UTC),
    )
    state.set_answer(replace(game, correct_option="A", answer_source_url="https://example.com"))

    result = score_responses(
        ScoreResponsesConfig(
            scoring_date=date(2026, 8, 11), game_date=game_day, sender="organizer@example.com", organizer="organizer@example.com",
            gmail_user="organizer@example.com", oauth_client_id="client", oauth_client_secret="secret", oauth_refresh_token="token",
            state_store=state, dry_run=True,
        ),
        fetch_messages=lambda _query: [],
    )

    assert state.find_game(day=game_day).status == GAME_SCORED  # type: ignore[union-attr]
    assert len(state.outbound_messages) == 1
    outbound = next(iter(state.outbound_messages.values()))
    assert outbound.status == OUTBOUND_PENDING
    assert outbound.message_type == "organizer_scoring_update"
    assert result.organizer_message_id == outbound.id


def test_automated_publication_rolls_forward_only_a_scored_game() -> None:
    state = InMemoryAdapter()
    previous_day = date(2026, 8, 10)
    game = publish_manual_game(
        state=state, game_day=previous_day,
        question=Question(game_date=previous_day.isoformat(), prompt="Previous?", options={"A": "One", "B": "Two", "C": "Three", "D": "Four"}, correct_option="", source_note="Source", source_url="https://example.com", source="manual"),
        message_id="question", published_at=datetime(2026, 8, 10, tzinfo=UTC),
    )
    state.set_answer(replace(game, correct_option="A", answer_source_url="https://example.com"))

    unscored = send_question(
        SendQuestionConfig(
            game_date=date(2026, 8, 11), sender="organizer@example.com", gmail_user="organizer@example.com",
            oauth_client_id="client", oauth_client_secret="secret", oauth_refresh_token="token", state_store=state,
            google_group_email="players@example.com", dry_run=True,
        ),
        fetch_messages=lambda _query: [],
    )
    assert "The Answer on 2026-08-10" not in unscored.email_body

    state.score_game(replace(game, scored_at=datetime(2026, 8, 11, tzinfo=UTC)))
    scored = send_question(
        SendQuestionConfig(
            game_date=date(2026, 8, 12), sender="organizer@example.com", gmail_user="organizer@example.com",
            oauth_client_id="client", oauth_client_secret="secret", oauth_refresh_token="token", state_store=state,
            google_group_email="players@example.com", dry_run=True,
        ),
        fetch_messages=lambda _query: [],
    )
    assert "The Answer on 2026-08-10 is A" in scored.email_body


def test_next_player_email_recaps_prior_game_point_earners_with_nicknames() -> None:
    state = InMemoryAdapter()
    game_day = date(2026, 8, 10)
    game = publish_manual_game(
        state=state, game_day=game_day,
        question=Question(
            game_date=game_day.isoformat(), prompt="Previous?",
            options={"A": "One", "B": "Two", "C": "Three", "D": "Four"},
            correct_option="", source_note="Source", source_url="https://example.com", source="manual",
        ),
        message_id="question", published_at=datetime(2026, 8, 10, tzinfo=UTC),
    )
    state.set_answer(replace(game, correct_option="A", answer_source_url="https://example.com"))
    ada = state.create_or_find_player(email="ada@example.com")
    state.players[ada.id] = replace(ada, nickname="Ada")
    ben = state.create_or_find_player(email="ben@example.com")
    state.players[ben.id] = replace(ben, nickname="Ben")

    score_responses(
        ScoreResponsesConfig(
            scoring_date=date(2026, 8, 11), game_date=game_day, sender="organizer@example.com",
            organizer="organizer@example.com", gmail_user="organizer@example.com", oauth_client_id="client",
            oauth_client_secret="secret", oauth_refresh_token="token", state_store=state, dry_run=True,
        ),
        fetch_messages=lambda _query: [
            ParsedEmailMessage("ada-reply", "thread", "ada@example.com", "QOTD - 08-10-26", datetime(2026, 8, 10, 18, tzinfo=UTC), "A"),
            ParsedEmailMessage("ben-reply", "thread", "ben@example.com", "QOTD - 08-10-26", datetime(2026, 8, 10, 18, tzinfo=UTC), "B"),
        ],
    )

    result = send_question(
        SendQuestionConfig(
            game_date=date(2026, 8, 11), sender="organizer@example.com", gmail_user="organizer@example.com",
            oauth_client_id="client", oauth_client_secret="secret", oauth_refresh_token="token", state_store=state,
            google_group_email="players@example.com", dry_run=True,
        ),
        fetch_messages=lambda _query: [],
    )

    assert "Points earned:\n- Ada" in result.email_body
    assert "Points earned:\n- Ben" not in result.email_body
    assert "1. Ada — 1" in result.email_body
    assert "2. Ben — 0" in result.email_body


def test_automatic_scoring_preserves_an_existing_manual_score_event() -> None:
    state = InMemoryAdapter()
    game_day = date(2026, 8, 10)
    game = publish_manual_game(
        state=state, game_day=game_day,
        question=Question(game_date=game_day.isoformat(), prompt="Question?", options={"A": "One", "B": "Two", "C": "Three", "D": "Four"}, correct_option="", source_note="", source_url="", source="manual"),
        message_id="question", published_at=datetime(2026, 8, 10, tzinfo=UTC),
    )
    state.set_answer(replace(game, correct_option="A", answer_source_url="https://example.com"))
    record_manual_score_event(
        ManualScoreEventConfig(email="ada@example.com", points_delta=2, reason="correction", state_store=state, game_date=game_day)
    )

    score_responses(
        ScoreResponsesConfig(
            scoring_date=date(2026, 8, 11), game_date=game_day, sender="organizer@example.com", organizer="organizer@example.com",
            gmail_user="organizer@example.com", oauth_client_id="client", oauth_client_secret="secret", oauth_refresh_token="token",
            state_store=state, dry_run=True,
        ),
        fetch_messages=lambda _query: [ParsedEmailMessage("reply", "thread", "ada@example.com", "QOTD - 08-10-26", datetime(2026, 8, 10, 18, tzinfo=UTC), "A")],
    )

    assert state.read_scoreboard(series_id=game.series_id)[0].score == 3


def test_automated_publication_uses_canonical_state() -> None:
    state = InMemoryAdapter()
    game_day = date(2026, 8, 10)
    result = send_question(
        SendQuestionConfig(
            game_date=game_day,
            sender="organizer@example.com",
            gmail_user="organizer@example.com",
            oauth_client_id="client",
            oauth_client_secret="secret",
            oauth_refresh_token="token",
            google_group_email="players@example.com",
            state_store=state,
            question_generator=lambda day, _state: Question(
                game_date=day.isoformat(), prompt="Question?",
                options={"A": "One", "B": "Two", "C": "Three", "D": "Four"},
                correct_option="A", source_note="Source", source_url="https://example.com/source",
            ),
            dry_run=True,
        ),
        fetch_messages=lambda _query: [],
    )

    game = state.find_game(day=game_day)
    assert game is not None
    assert game.status == "published"
    assert result.record.correct_option == "A"


def _publication_config(state: InMemoryAdapter) -> SendQuestionConfig:
    game_day = date(2026, 8, 10)
    return SendQuestionConfig(
        game_date=game_day, sender="organizer@example.com", gmail_user="organizer@example.com",
        oauth_client_id="client", oauth_client_secret="secret", oauth_refresh_token="token",
        google_group_email="players@example.com", state_store=state,
        question_generator=lambda day, _state: Question(
            game_date=day.isoformat(), prompt="Question?", options={"A": "One", "B": "Two", "C": "Three", "D": "Four"},
            correct_option="A", source_note="Source", source_url="https://example.com/source",
        ),
    )


def test_publication_send_failure_leaves_one_pending_intent() -> None:
    state = InMemoryAdapter()

    with pytest.raises(RuntimeError, match="send failed"):
        send_question(
            _publication_config(state), fetch_messages=lambda _query: [],
            send_message=lambda _message: (_ for _ in ()).throw(RuntimeError("send failed")),
        )

    assert state.find_game(day=date(2026, 8, 10)) is not None
    assert len(state.outbound_messages) == 1
    assert next(iter(state.outbound_messages.values())).status == OUTBOUND_PENDING


def test_pending_publication_reconciles_without_another_send() -> None:
    state = InMemoryAdapter()
    config = _publication_config(state)
    with pytest.raises(RuntimeError, match="send failed"):
        send_question(
            config, fetch_messages=lambda _query: [],
            send_message=lambda _message: (_ for _ in ()).throw(RuntimeError("send failed")),
        )
    intent = next(iter(state.outbound_messages.values()))
    sends: list[EmailMessage] = []

    def record_unexpected_send(message: EmailMessage) -> str:
        sends.append(message)
        return "unexpected"

    result = send_question(
        config,
        fetch_messages=lambda _query: [
            ParsedEmailMessage("sent-message", "thread", "organizer@example.com", intent.subject, intent.created_at, intent.body_text)
        ],
        send_message=record_unexpected_send,
    )

    assert result.reason == "publication_intent_already_exists"
    assert not sends
    assert next(iter(state.outbound_messages.values())).status == OUTBOUND_SENT


def test_ambiguous_pending_publication_never_sends_a_duplicate() -> None:
    state = InMemoryAdapter()
    config = _publication_config(state)
    with pytest.raises(RuntimeError, match="send failed"):
        send_question(config, fetch_messages=lambda _query: [], send_message=lambda _message: (_ for _ in ()).throw(RuntimeError("send failed")))
    intent = next(iter(state.outbound_messages.values()))
    sends: list[EmailMessage] = []
    matches = [
        ParsedEmailMessage(f"sent-{index}", "thread", "organizer@example.com", intent.subject, datetime(2026, 8, 10, tzinfo=UTC), intent.body_text)
        for index in range(2)
    ]

    def record_unexpected_send(message: EmailMessage) -> str:
        sends.append(message)
        return "unexpected"

    with pytest.raises(RuntimeError, match="uniquely reconciled"):
        send_question(config, fetch_messages=lambda _query: matches, send_message=record_unexpected_send)

    assert not sends
    assert next(iter(state.outbound_messages.values())).status == OUTBOUND_PENDING


def test_successful_publication_commits_game_and_marks_its_intent_sent() -> None:
    state = InMemoryAdapter()

    send_question(_publication_config(state), fetch_messages=lambda _query: [], send_message=lambda _message: "sent-message")

    assert state.find_game(day=date(2026, 8, 10)) is not None
    assert len(state.outbound_messages) == 1
    outbound = next(iter(state.outbound_messages.values()))
    assert outbound.status == OUTBOUND_SENT
    game = state.find_game(day=date(2026, 8, 10))
    assert outbound.game_id == game.id  # type: ignore[union-attr]


def test_missing_answer_creates_one_organizer_intent_without_score_events() -> None:
    state = InMemoryAdapter()
    game_day = date(2026, 8, 10)
    publish_manual_game(
        state=state,
        game_day=game_day,
        question=Question(
            game_date=game_day.isoformat(), prompt="Question?",
            options={"A": "One", "B": "Two", "C": "Three", "D": "Four"},
            correct_option="", source_note="", source_url="", source="manual",
        ),
        message_id="manual-question", published_at=datetime(2026, 8, 10, tzinfo=UTC),
    )

    config = ScoreResponsesConfig(
        scoring_date=date(2026, 8, 11), game_date=game_day,
        sender="organizer@example.com", organizer="organizer@example.com", gmail_user="organizer@example.com",
        oauth_client_id="client", oauth_client_secret="secret", oauth_refresh_token="token",
        state_store=state, dry_run=True,
    )
    first = score_responses(config)
    second = score_responses(config)

    assert first.skipped_reason == "missing_correct_answer"
    assert second.organizer_message_id == first.organizer_message_id
    assert len(state.outbound_messages) == 1
    assert state.score_events == {}


def test_manual_question_publication_uses_the_pending_answer() -> None:
    state = InMemoryAdapter()
    game_day = date(2026, 8, 10)
    apply_answer_instruction(
        state=state,
        message=ParsedEmailMessage(
            message_id="answer", thread_id="thread", sender_email="organizer@example.com", subject="Answer",
            sent_at=datetime(2026, 8, 9, tzinfo=UTC),
            body_text="Action: set-answer\nDay: 2026-08-10\nCorrect option: B\nSource URL: https://example.com/source",
        ),
        processed_at=datetime(2026, 8, 9, tzinfo=UTC),
    )

    result = send_question(
        SendQuestionConfig(
            game_date=game_day, sender="organizer@example.com", gmail_user="organizer@example.com",
            oauth_client_id="client", oauth_client_secret="secret", oauth_refresh_token="token", state_store=state,
        ),
        fetch_messages=lambda _query: [
            ParsedEmailMessage(
                message_id="manual-question", thread_id="thread", sender_email="organizer@example.com",
                subject="QOTD - 08-10-26", sent_at=datetime(2026, 8, 10, tzinfo=UTC),
                body_text="Question?\nA. One\nB. Two\nC. Three\nD. Four",
            )
        ],
    )

    assert result.skipped_generated_send
    assert state.find_game(day=game_day).correct_option == "B"  # type: ignore[union-attr]


def test_manual_scoring_succeeds_after_an_organizer_sets_the_missing_answer() -> None:
    state = InMemoryAdapter()
    now = datetime(2026, 8, 10, tzinfo=UTC)
    game_day = date(2026, 8, 10)
    game = publish_manual_game(
        state=state, game_day=game_day,
        question=Question(game_date=game_day.isoformat(), prompt="Question?", options={"A": "One", "B": "Two", "C": "Three", "D": "Four"}, correct_option="", source_note="", source_url="", source="manual"),
        message_id="manual", published_at=now,
    )
    apply_answer_instruction(
        state=state,
        message=ParsedEmailMessage(
            message_id="answer", thread_id="thread", sender_email="organizer@example.com", subject="Answer", sent_at=now,
            body_text="Action: set-answer\nDay: 2026-08-10\nCorrect option: A\nSource URL: https://example.com/source",
        ),
        processed_at=now,
    )
    player = state.create_or_find_player(email="player@example.com")
    state.record_submission(Submission(new_id(), "reply", game.id, player.id, "A", now, True, now, now))

    result = score_responses(
        ScoreResponsesConfig(
            scoring_date=date(2026, 8, 11), game_date=game_day,
            sender="organizer@example.com", organizer="organizer@example.com", gmail_user="organizer@example.com",
            oauth_client_id="client", oauth_client_secret="secret", oauth_refresh_token="token",
            state_store=state, dry_run=True,
        ),
        fetch_messages=lambda _query: [],
    )

    assert result.skipped_reason is None
    assert state.find_game(day=game_day).status == GAME_SCORED  # type: ignore[union-attr]
