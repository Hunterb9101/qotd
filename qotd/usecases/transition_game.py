"""Transition canonical Games through lifecycle states."""

from __future__ import annotations

from dataclasses import dataclass

from qotd.domain.canonical import Game, OutboundMessage, ScoreEvent
from qotd.external.storage.canonical import CanonicalState


@dataclass(frozen=True)
class ScoreGameTransition:
    """The atomic state changes produced when a Game is scored."""

    game: Game
    score_events: tuple[ScoreEvent, ...]
    outbound_messages: tuple[OutboundMessage, ...] = ()


def score_game_transition(*, state: CanonicalState, transition: ScoreGameTransition) -> Game:
    """Score a published Game with its immutable events in one state transition."""

    return state.score_game(
        transition.game,
        score_events=transition.score_events,
        outbound_messages=transition.outbound_messages,
    )
