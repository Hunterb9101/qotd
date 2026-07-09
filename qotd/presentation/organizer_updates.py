"""Organizer-facing scoring update presentation."""

from __future__ import annotations

from qotd.domain.models import StoredQuestion
from qotd.domain.scoring import ScoringResult
from qotd.presentation.rendering import render_template


def build_organizer_update_body(question: StoredQuestion, result: ScoringResult) -> str:
    """Build the organizer-only scoring update body."""

    return render_template("organizer_update.txt.j2", question=question, result=result)
