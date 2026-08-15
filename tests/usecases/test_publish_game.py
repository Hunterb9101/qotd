from datetime import UTC, date, datetime

from qotd.domain.canonical import Game
from qotd.domain.models import Question
from qotd.usecases.handle_answer import apply_answer_instruction
from qotd.usecases.publish_game import publish_automated_game, publish_manual_game
from qotd.usecases.check_manual_question import check_manual_question
from qotd.external.email.core import ParsedEmailMessage
from qotd.external.storage.memory import InMemoryAdapter


def _question(game_day: date, correct_option: str = "A") -> Question:
    return Question(
        game_date=game_day.isoformat(), prompt="Question?", options={"A": "One", "B": "Two", "C": "Three", "D": "Four"},
        correct_option=correct_option, source_note="Source note", source_url="https://example.com/source",
    )


def _answer_message() -> ParsedEmailMessage:
    return ParsedEmailMessage(
        message_id="answer-1", thread_id="thread-1", sender_email="organizer@example.com", subject="Answer",
        sent_at=datetime(2026, 8, 9, tzinfo=UTC),
        body_text="Action: set-answer\nDay: 2026-08-10\nCorrect option: B\nSource URL: https://example.com/source",
    )


def test_publish_game_manually_attaches_the_pending_answer() -> None:
    state = InMemoryAdapter()
    apply_answer_instruction(state=state, message=_answer_message(), processed_at=datetime(2026, 8, 9, tzinfo=UTC))

    game = publish_manual_game(
        state=state, game_day=date(2026, 8, 10), question=_question(date(2026, 8, 10)),
        message_id="manual-question-1", published_at=datetime(2026, 8, 10, tzinfo=UTC),
    )

    assert game.status == "published"
    assert game.correct_option == "B"


def test_automated_publication_discards_a_pending_answer() -> None:
    state = InMemoryAdapter()
    apply_answer_instruction(state=state, message=_answer_message(), processed_at=datetime(2026, 8, 9, tzinfo=UTC))

    game = publish_automated_game(
        state=state, game_day=date(2026, 8, 10), question=_question(date(2026, 8, 10), correct_option="C"),
        message_id="automated-question-1", published_at=datetime(2026, 8, 10, tzinfo=UTC),
    )

    assert game.status == "published"
    assert game.correct_option == "C"


def test_detected_manual_question_creates_a_publication_outbound_message() -> None:
    """A Gmail-detected Question has a durable publication record correlated to its Game."""

    state = InMemoryAdapter()
    game_day = date(2026, 8, 10)
    game = check_manual_question(
        game_date=game_day,
        sender="organizer@example.com",
        state=state,
        fetch_messages=lambda _query: [
            ParsedEmailMessage(
                message_id="gmail-question-1", thread_id="thread-1", sender_email="organizer@example.com",
                subject="QOTD - 08-10-26", sent_at=datetime(2026, 8, 10, tzinfo=UTC),
                body_text="Which option?\nA. One\nB. Two\nC. Three\nD. Four",
            )
        ],
    )

    assert game is not None
    assert isinstance(game, Game)
    outbound = next(
        message for message in state.outbound_messages.values()
        if message.game_id == game.id and message.message_type == "question_publication"
    )
    assert outbound.source_message_key == game.publication_message_key
