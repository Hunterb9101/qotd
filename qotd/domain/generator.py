"""Question generation for the noon QOTD send workflow."""

from __future__ import annotations

import random

from qotd.domain.models import OPTION_LABELS, Question


def shuffle_answer_options(options: dict[str, str], correct_option: str) -> tuple[dict[str, str], str]:
    """Randomize option placement while retaining the correct answer."""

    answers = list(options.items())
    random.shuffle(answers)
    shuffled_options = {
        label: answer
        for label, (_, answer) in zip(OPTION_LABELS, answers, strict=True)
    }
    shuffled_correct_option = next(
        label for label, (original_label, _) in zip(OPTION_LABELS, answers, strict=True)
        if original_label == correct_option
    )
    return shuffled_options, shuffled_correct_option


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
