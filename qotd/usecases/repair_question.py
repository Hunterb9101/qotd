"""Repair a rejected generated QOTD Question without changing its research context."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict

from qotd.domain.generator import shuffle_answer_options
from qotd.domain.models import GeneratedQuestionCandidate, Question
from qotd.external.llm.core import LLMClient


DEFAULT_REPAIR_PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "repair_generated_question.md"


class RepairedQuestionOptions(BaseModel):
    """The four labeled answer options returned by the repair call."""

    model_config = ConfigDict(extra="forbid")

    A: str
    B: str
    C: str
    D: str


class RepairedQuestionOutput(BaseModel):
    """Structured question fields returned by the repair call."""

    model_config = ConfigDict(extra="forbid")

    prompt: str
    options: RepairedQuestionOptions
    correct_option: Literal["A", "B", "C", "D"]
    source_note: str


class QuestionRepairer(Protocol):
    """Repair a rejected candidate without changing its topic or evidence."""

    def __call__(
        self,
        candidate: GeneratedQuestionCandidate,
        issues: tuple[str, ...],
        /,
    ) -> GeneratedQuestionCandidate:
        """Return a focused revision of the supplied candidate."""


@dataclass(frozen=True)
class RepairGeneratedQuestion:
    """Repair a candidate using the provider-neutral LLM client."""

    llm_client: LLMClient
    prompt_path: Path = DEFAULT_REPAIR_PROMPT_PATH
    max_output_tokens: int = 8000

    def __call__(
        self,
        candidate: GeneratedQuestionCandidate,
        issues: tuple[str, ...],
        /,
    ) -> GeneratedQuestionCandidate:
        """Return a minimally revised candidate that addresses the supplied issues."""

        question = candidate.question
        data = self.llm_client.create_structured_response(
            prompt_path=self.prompt_path,
            payload={
                "category": candidate.category,
                "topic": candidate.topic,
                "question": {
                    "prompt": question.prompt,
                    "options": question.options,
                    "correct_option": question.correct_option,
                    "correct_answer": question.options.get(question.correct_option, ""),
                    "source_note": question.source_note,
                },
                "sources": [
                    {"url": url, "evidence": evidence}
                    for url, evidence in zip(
                        candidate.source_urls,
                        candidate.source_evidence,
                        strict=True,
                    )
                ],
                "issues": list(issues),
            },
            response_model=RepairedQuestionOutput,
            schema_name="qotd_repaired_question",
            max_output_tokens=self.max_output_tokens,
        )
        options, correct_option = shuffle_answer_options(
            data.options.model_dump(), data.correct_option
        )
        return GeneratedQuestionCandidate(
            question=Question(
                game_date=question.game_date,
                prompt=data.prompt,
                options=options,
                correct_option=correct_option,
                source_note=data.source_note,
                source_url=question.source_url,
            ),
            topic_source=candidate.topic_source,
            category=candidate.category,
            topic=candidate.topic,
            source_urls=candidate.source_urls,
            source_evidence=candidate.source_evidence,
        )
