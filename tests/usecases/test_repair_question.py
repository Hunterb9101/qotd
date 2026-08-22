"""Live evaluations for repairing generated Questions."""

from __future__ import annotations

from datetime import date
import os

import pytest

from qotd.domain.models import GeneratedQuestionCandidate, Question, QuestionTopic
from qotd.external.llm.openai import build_openai_llm_client
from qotd.external.storage.memory import InMemoryAdapter
from qotd.usecases.generate_question import validate_self_researched_candidate
from qotd.usecases.repair_question import RepairGeneratedQuestion


def _api_key() -> str:
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        pytest.fail(
            "OPENAI_API_KEY is required for the explicitly selected live intg suite",
            pytrace=False,
        )
    return api_key


@pytest.mark.intg
def test_repair_question_removes_answer_leak_from_player_prompt() -> None:
    """The repair model must correct the answer leak seen in workflow run #59."""

    candidate = GeneratedQuestionCandidate(
        question=Question(
            game_date=date(2026, 7, 10).isoformat(),
            prompt="Amazon actually lets you swap the wake word on an Echo. Which wake word is on the available list?",
            options={"A": "Siri", "B": "Amazon", "C": "Cortana", "D": "Bixby"},
            correct_option="B",
            source_note="Amazon documents the available Alexa wake words.",
            source_url="https://www.amazon.com/gp/help/customer/display.html?nodeId=GKLXVX2X7B8P6Q5C",
        ),
        topic_source=QuestionTopic(
            title="Alexa wake words",
            summary="Amazon documents alternate wake words for Echo devices.",
            source_url="https://www.amazon.com/gp/help/customer/display.html?nodeId=GKLXVX2X7B8P6Q5C",
        ),
        category="Technology",
        topic="Alexa wake words",
        source_urls=("https://www.amazon.com/gp/help/customer/display.html?nodeId=GKLXVX2X7B8P6Q5C",),
        source_evidence=("Amazon is available as an Alexa wake word.",),
    )
    repair = RepairGeneratedQuestion(
        llm_client=build_openai_llm_client(
            api_key=_api_key(),
            model=os.environ.get("OPENAI_GENERATOR_MODEL", "gpt-5.4-mini"),
            state=InMemoryAdapter(),
        )
    )

    repaired = repair(candidate, ("question prompt leaks the correct answer",))

    assert repaired.question.prompt != candidate.question.prompt
    assert "amazon" not in repaired.question.prompt.casefold()
    validate_self_researched_candidate(repaired)
