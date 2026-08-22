"""Live evaluations for repairing generated Questions."""

from __future__ import annotations

from datetime import date
import os

import pytest

from qotd.domain.models import GeneratedQuestionCandidate, Question, QuestionTopic
from qotd.external.llm.openai import build_openai_llm_client
from qotd.external.storage.memory import InMemoryAdapter
from qotd.usecases.generate_question import LLMQuestionEvaluator, validate_self_researched_candidate
from qotd.usecases.repair_question import RepairGeneratedQuestion


def _api_key() -> str:
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        pytest.fail(
            "OPENAI_API_KEY is required for the explicitly selected live intg suite",
            pytrace=False,
        )
    return api_key


def _live_llm_client():
    return build_openai_llm_client(
        api_key=_api_key(),
        model=os.environ.get("OPENAI_GENERATOR_MODEL", "gpt-5.4-mini"),
        state=InMemoryAdapter(),
    )


def _repair(candidate: GeneratedQuestionCandidate) -> GeneratedQuestionCandidate:
    repair = RepairGeneratedQuestion(llm_client=_live_llm_client())
    return repair(candidate, ("question prompt leaks the correct answer",))


def _evaluate(candidate: GeneratedQuestionCandidate) -> tuple[str, ...]:
    return LLMQuestionEvaluator(llm_client=_live_llm_client())(candidate)


@pytest.mark.intg
def test_repair_question_removes_answer_leak_from_player_prompt() -> None:
    """The repair model must correct the answer leak seen in workflow run #59."""

    candidate = GeneratedQuestionCandidate(
        question=Question(
            game_date=date(2026, 7, 10).isoformat(),
            prompt="Ziggy is one of the wake words available on an Amazon Echo. Which wake word can you choose?",
            options={"A": "Nova", "B": "Ziggy", "C": "Orbit", "D": "Nimbus"},
            correct_option="B",
            source_note="Amazon documents the available Echo wake words.",
            source_url="https://www.amazon.com/gp/help/customer/display.html?nodeId=GKLXVX2X7B8P6Q5C",
        ),
        topic_source=QuestionTopic(
            title="Echo wake words",
            summary="Amazon documents alternate wake words for Echo devices.",
            source_url="https://www.amazon.com/gp/help/customer/display.html?nodeId=GKLXVX2X7B8P6Q5C",
        ),
        category="Technology",
        topic="Echo wake words",
        source_urls=("https://www.amazon.com/gp/help/customer/display.html?nodeId=GKLXVX2X7B8P6Q5C",),
        source_evidence=("Echo wake words include Alexa, Amazon, Computer, Echo, and Ziggy.",),
    )
    repaired = _repair(candidate)

    assert repaired.question.prompt != candidate.question.prompt
    assert "ziggy" not in repaired.question.prompt.casefold()
    assert "echo" in repaired.question.prompt.casefold()
    validate_self_researched_candidate(repaired)
    assert _evaluate(repaired) == ()


@pytest.mark.intg
def test_repair_question_removes_city_answer_leak_from_player_prompt() -> None:
    """The repair model removes an answer leaked by descriptive setup wording."""

    candidate = GeneratedQuestionCandidate(
        question=Question(
            game_date=date(2026, 7, 10).isoformat(),
            prompt=(
                "Here's a weirdly St. Louis dessert crossover for you: gooey butter cake is one "
                "of those happy accidents people can't stop talking about. What city is it tied to?"
            ),
            options={
                "A": "Savannah, Georgia",
                "B": "Providence, Rhode Island",
                "C": "St. Louis, Missouri",
                "D": "Portland, Oregon",
            },
            correct_option="C",
            source_note="Gooey butter cake originated in St. Louis, Missouri.",
            source_url="https://www.explorestlouis.com/food-drink/gooey-butter-cake/",
        ),
        topic_source=QuestionTopic(
            title="Gooey butter cake",
            summary="A dessert associated with a baking accident.",
            source_url="https://www.explorestlouis.com/food-drink/gooey-butter-cake/",
        ),
        category="Food & Drink",
        topic="Gooey butter cake",
        source_urls=("https://www.explorestlouis.com/food-drink/gooey-butter-cake/",),
        source_evidence=("Gooey butter cake originated in St. Louis, Missouri.",),
    )

    repaired = _repair(candidate)

    assert repaired.question.prompt != candidate.question.prompt
    assert "st. louis" not in repaired.question.prompt.casefold()
    validate_self_researched_candidate(repaired)
    assert _evaluate(repaired) == ()
