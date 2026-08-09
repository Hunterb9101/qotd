"""Live evaluations for the production answer interpreter."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from qotd.domain.models import StoredQuestion
from qotd.external.llm.openai import build_openai_llm_client
from qotd.usecases.score_submissions import LLMAnswerInterpreter


CASES_PATH = Path(__file__).with_name("answer_interpretation_cases.json")
CASES = json.loads(CASES_PATH.read_text(encoding="utf-8"))


def _api_key() -> str:
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        pytest.fail(
            "OPENAI_API_KEY is required for the explicitly selected live intg suite",
            pytrace=False,
        )
    return api_key


@pytest.mark.intg
@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
def test_score_submissions_live_answer_interpretation(case: dict[str, object]) -> None:
    question = StoredQuestion(
        game_date="2026-07-11",
        prompt="Which planet has the Great Red Spot?",
        options={"A": "Mars", "B": "Jupiter", "C": "Saturn", "D": "Neptune"},
        correct_option="B",
        source_note="NASA identifies Jupiter's Great Red Spot.",
        source_url="https://science.nasa.gov/jupiter/",
        source="integration-fixture",
        gmail_message_id="integration-fixture",
        created_at="2026-07-11T12:00:00+00:00",
    )
    interpreter = LLMAnswerInterpreter(
        llm_client=build_openai_llm_client(
            api_key=_api_key(),
            model=os.environ.get("OPENAI_INTERPRETER_MODEL", "gpt-4.1-mini"),
        ),
        question=question,
    )

    actual = interpreter(str(case["reply"]))

    assert (actual.option, actual.needs_review) == (
        case["expected_option"],
        case["expected_needs_review"],
    ), (
        f"fixture={case['id']!r}, expected="
        f"({case['expected_option']!r}, {case['expected_needs_review']!r}), "
        f"actual=({actual.option!r}, {actual.needs_review!r})"
    )
