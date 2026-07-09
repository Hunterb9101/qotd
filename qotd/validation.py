"""Validation helpers for structured QOTD questions."""

from __future__ import annotations

from urllib.parse import urlparse

from qotd.models import OPTION_LABELS, Question


def validate_question(question: Question) -> None:
    """Validate the minimal generated-question contract."""

    option_labels = set(question.options)
    if option_labels != set(OPTION_LABELS):
        raise ValueError("question must include exactly A, B, C, and D options")

    option_values = [value.strip() for value in question.options.values()]
    if any(not value for value in option_values):
        raise ValueError("question options cannot be blank")
    if len({value.casefold() for value in option_values}) != len(option_values):
        raise ValueError("question options must not repeat")

    if question.correct_option not in OPTION_LABELS:
        raise ValueError("correct_option must be one of A, B, C, or D")

    parsed_url = urlparse(question.source_url)
    if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
        raise ValueError("source_url must be a valid http or https URL")

    if not question.prompt.strip():
        raise ValueError("question prompt cannot be blank")

