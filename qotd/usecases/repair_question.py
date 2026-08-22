"""Repair a rejected generated QOTD Question without changing its research context."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict

from qotd.domain.generator import shuffle_answer_options
from qotd.domain.models import GeneratedQuestionCandidate, Question
from qotd.external.llm.core import LLMClient
from qotd.domain.canonical import new_id


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
    usecase_run_id: str = ""

    def __call__(
        self,
        candidate: GeneratedQuestionCandidate,
        issues: tuple[str, ...],
        /,
    ) -> GeneratedQuestionCandidate:
        """Return a minimally revised candidate that addresses the supplied issues."""

        question = candidate.question
        repairing_answer_leak = "question prompt leaks the correct answer" in issues
        if repairing_answer_leak:
            repair_topic = "a trivia fact"
            repair_question = {
                "prompt": "Write a new Player-facing question for the supplied fact.",
                "options": {
                    label: "[REDACTED CORRECT ANSWER]" if label == question.correct_option else option
                    for label, option in question.options.items()
                },
                "correct_option": question.correct_option,
                "correct_answer": "[REDACTED CORRECT ANSWER]",
                "source_note": "An authoritative source supports the correct answer.",
            }
            repair_sources = ({"url": "[REDACTED SOURCE]", "evidence": "The source supports the correct answer."},)
        else:
            repair_topic = candidate.topic
            repair_question = {
                "prompt": question.prompt,
                "options": question.options,
                "correct_option": question.correct_option,
                "correct_answer": question.options.get(question.correct_option, ""),
                "source_note": question.source_note,
            }
            repair_sources = tuple(
                {"url": url, "evidence": evidence}
                for url, evidence in zip(
                    candidate.source_urls,
                    candidate.source_evidence,
                    strict=True,
                )
            )

        data = self.llm_client.create_structured_response(
            prompt_path=self.prompt_path,
            payload={
                "category": candidate.category,
                "topic": repair_topic,
                "question": repair_question,
                "sources": repair_sources,
                "issues": list(issues),
            },
            response_model=RepairedQuestionOutput,
            schema_name="qotd_repaired_question",
            max_output_tokens=self.max_output_tokens,
            use_case="publish_question",
            usecase_run_id=self.usecase_run_id or new_id(),
        )
        if repairing_answer_leak:
            repaired_options = question.options
            repaired_correct_option = question.correct_option
            repaired_source_note = question.source_note
        else:
            repaired_options = data.options.model_dump()
            repaired_correct_option = data.correct_option
            repaired_source_note = data.source_note
        options, correct_option = shuffle_answer_options(
            repaired_options, repaired_correct_option
        )
        return GeneratedQuestionCandidate(
            question=Question(
                game_date=question.game_date,
                prompt=data.prompt,
                options=options,
                correct_option=correct_option,
                source_note=repaired_source_note,
                source_url=question.source_url,
            ),
            topic_source=candidate.topic_source,
            category=candidate.category,
            topic=candidate.topic,
            source_urls=candidate.source_urls,
            source_evidence=candidate.source_evidence,
        )
