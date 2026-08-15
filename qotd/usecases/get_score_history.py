"""Get Player-facing Scoreboard history."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from qotd.domain.models import ScoreboardLine
from qotd.external.storage.canonical import CanonicalState


@dataclass(frozen=True)
class PlayerResults:
    """Finalized scoring details suitable for a Player recap."""

    point_earners: tuple[str, ...]
    standings: tuple[ScoreboardLine, ...]


def load_player_results(state_store: CanonicalState, game_date: date) -> PlayerResults:
    """Load a Day's canonical Series Scoreboard for Player-facing rendering."""

    game = state_store.find_game(day=game_date)
    if game is None:
        return PlayerResults(point_earners=(), standings=())
    scoreboard = state_store.read_scoreboard(series_id=game.series_id)
    player_names = {entry.player_id: entry.nickname or entry.email for entry in scoreboard}
    point_earner_ids = {
        event.player_id
        for event in state_store.read_score_events_for_game(game_id=game.id)
        if event.points_delta > 0
    }
    return PlayerResults(
        point_earners=tuple(
            player_names[entry.player_id] for entry in scoreboard if entry.player_id in point_earner_ids
        ),
        standings=tuple(
            ScoreboardLine(
                series=game.day.strftime("%m%y"), email=entry.email, points=entry.score, nickname=entry.nickname
            )
            for entry in scoreboard
        ),
    )
