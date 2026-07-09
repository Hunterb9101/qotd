"""Question generation for the noon QOTD send workflow."""

from __future__ import annotations

from qotd.models import Question


def generate_placeholder_question(game_date: str) -> Question:
    """Return a deterministic placeholder question until AI generation is defined."""

    return Question(
        game_date=game_date,
        prompt="Which planet in our solar system is known for having the Great Red Spot?",
        options={
            "A": "Mars",
            "B": "Jupiter",
            "C": "Saturn",
            "D": "Neptune",
        },
        correct_option="B",
        source_note="NASA describes Jupiter's Great Red Spot as a long-lived storm.",
        source_url="https://science.nasa.gov/jupiter/jupiter-facts/",
    )

