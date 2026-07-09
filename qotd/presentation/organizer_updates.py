"""Organizer-facing scoring update presentation."""

from __future__ import annotations

from datetime import date

from qotd.domain.dates import is_final_weekday_of_month
from qotd.domain.models import StoredQuestion
from qotd.domain.scoring import ScoringResult
from qotd.presentation.rendering import render_template


def build_organizer_update_body(question: StoredQuestion, result: ScoringResult) -> str:
    """Build the organizer-only scoring update body."""

    game_date = date.fromisoformat(question.game_date)
    max_points = max((score.points for score in result.standings), default=None)
    winners = tuple(score for score in result.standings if max_points is not None and score.points == max_points)
    return render_template(
        "organizer_update.txt.j2",
        question=question,
        result=result,
        is_final_weekday=is_final_weekday_of_month(game_date),
        winners=winners,
    )
