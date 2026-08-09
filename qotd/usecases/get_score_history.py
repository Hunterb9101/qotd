"""Get Player-facing Scoreboard history."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from qotd.domain.dates import monthly_series
from qotd.domain.models import MonthlyScore
from qotd.domain.scoring import latest_score_map, standings_from_scores
from qotd.external.storage.core import StorageClient


@dataclass(frozen=True)
class PlayerResults:
    """Finalized scoring details suitable for a Player recap."""

    point_earners: tuple[str, ...]
    standings: tuple[MonthlyScore, ...]


def load_player_results(state_store: StorageClient, game_date: date) -> PlayerResults:
    """Load point earners for a Day and its latest Series Scoreboard."""

    game_date_text = game_date.isoformat()
    latest_points_by_email: dict[str, int] = {}
    for record in state_store.read_reply_processing_records(game_date=game_date_text):
        email = record.get("email")
        points = record.get("points_awarded")
        if isinstance(email, str) and isinstance(points, int):
            latest_points_by_email[email] = points

    series = monthly_series(game_date)
    scores = latest_score_map(state_store.read_monthly_scores(series=series), series=series)
    return PlayerResults(
        point_earners=tuple(sorted(email for email, points in latest_points_by_email.items() if points > 0)),
        standings=standings_from_scores(series, scores),
    )
