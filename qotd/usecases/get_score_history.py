"""Get Player-facing Scoreboard history."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from qotd.domain.models import MonthlyScore
from qotd.external.storage.canonical import CanonicalState


@dataclass(frozen=True)
class PlayerResults:
    """Finalized scoring details suitable for a Player recap."""

    point_earners: tuple[str, ...]
    standings: tuple[MonthlyScore, ...]


def load_player_results(state_store: CanonicalState, game_date: date) -> PlayerResults:
    """Load a Day's canonical Series Scoreboard for Player-facing rendering."""

    game = state_store.find_game(day=game_date)
    if game is None:
        return PlayerResults(point_earners=(), standings=())
    scoreboard = state_store.read_scoreboard(series_id=game.series_id)
    return PlayerResults(
        point_earners=(),
        standings=tuple(
            MonthlyScore(series=game.day.strftime("%m%y"), email=entry.email, points=entry.score)
            for entry in scoreboard
        ),
    )
