from datetime import UTC, date, datetime
from dataclasses import replace

from qotd.domain.canonical import GAME_PENDING, GAME_SCORED, Game, ScoreEvent, Submission, new_id
from qotd.domain.models import Question
from qotd.external.email.core import ParsedEmailMessage
from qotd.usecases.handle_answer import apply_answer_instruction
from qotd.usecases.transition_game import ScoreGameTransition, score_game_transition
from qotd.usecases.publish_game import publish_manual_game
from qotd.usecases.score_submissions import ScoreResponsesConfig, score_responses
from qotd.usecases.send_question import SendQuestionConfig, send_question
from tests.support import InMemoryCanonicalState


def test_transition_game_writes_events_and_marks_the_published_game_scored() -> None:
    state = InMemoryCanonicalState()
    now = datetime(2026, 8, 11, tzinfo=UTC)
    series = state.create_or_find_series(name="August 2026", starts_on=date(2026, 8, 1), ends_on=date(2026, 8, 31))
    player = state.create_or_find_player(email="ada@example.com")
    game = state.publish_game(
        Game(new_id(), series.id, date(2026, 8, 10), GAME_PENDING, "manual", now, now, now, correct_option="A")
    )
    submission = state.record_submission(
        Submission(new_id(), "submission", game.id, player.id, "A", now, True, now, now)
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


def test_automated_publication_uses_canonical_state() -> None:
    state = InMemoryCanonicalState()
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


def test_missing_answer_creates_one_organizer_intent_without_score_events() -> None:
    state = InMemoryCanonicalState()
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
    state = InMemoryCanonicalState()
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
    state = InMemoryCanonicalState()
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
