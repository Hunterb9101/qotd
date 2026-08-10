"""Get Question history from canonical Games."""

from __future__ import annotations

from datetime import date

from qotd.domain.canonical import Game
from qotd.domain.models import StoredQuestion
from qotd.external.storage.canonical import CanonicalState


def stored_question_from_game(game: Game) -> StoredQuestion:
    """Adapt a canonical Game for Question rendering."""

    return StoredQuestion(
        game_date=game.day.isoformat(),
        prompt=game.question_prompt or "",
        options=game.question_options or {},
        correct_option=game.correct_option or "",
        source_note=game.answer_source_note or "",
        source_url=game.answer_source_url or "",
        source=game.publication_mode,
        gmail_message_id=game.publication_message_key or "",
        created_at=(game.published_at or game.created_at).isoformat(),
    )


def find_game_for_day(state: CanonicalState, game_day: date) -> Game | None:
    """Return the canonical Game for a Day."""

    return state.find_game(day=game_day)


def find_question_for_game_date(state: object, game_date: date) -> StoredQuestion | None:
    """Return the Game Question and its Answer for a Day."""

    game = find_game_for_day(_require_canonical_state(state), game_date)
    return stored_question_from_game(game) if game is not None else None


def load_question_for_game_date(state: object, game_date: date) -> StoredQuestion:
    """Load a Game Question for a Day or raise when none exists."""

    question = find_question_for_game_date(state, game_date)
    if question is None:
        raise RuntimeError(f"No stored QOTD question found for {game_date.isoformat()}")
    return question


def find_latest_answered_question_before(state: object, game_date: date) -> StoredQuestion | None:
    """Return the most recent earlier Game with a displayable Answer."""

    game = _require_canonical_state(state).find_latest_answered_game_before(day=game_date)
    return stored_question_from_game(game) if game is not None else None


def _require_canonical_state(state: object) -> CanonicalState:
    if not isinstance(state, CanonicalState):
        raise TypeError("canonical Game state is required")
    return state
