"""Generate and verify a QOTD question for one topic."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict

from qotd.external.llm.core import LLMClient
from qotd.domain.models import Question
from qotd.domain.validation import validate_question
from qotd.external.storage.core import StorageClient


DEFAULT_PROMPT_PATH = Path(__file__).resolve().parents[2] / "docs" / "prompts" / "generate_question_for_topic.md"


@dataclass(frozen=True)
class QuestionTopic:
    """A timely or curated topic that can inspire a generated QOTD."""

    title: str
    summary: str
    source_url: str


@dataclass(frozen=True)
class VerificationResult:
    """Result of checking whether a generated question is safe to send."""

    passed: bool
    source_urls: tuple[str, ...] = ()
    source_note: str = ""
    reason: str = ""
    confidence: str = "low"


@dataclass(frozen=True)
class GeneratedQuestionCandidate:
    """A generated question plus internal generation metadata."""

    question: Question
    topic_source: QuestionTopic
    category: str
    subcategory: str = ""
    topic: str = ""
    entities: tuple[str, ...] = ()


class QuestionOptionsOutput(BaseModel):
    """Structured answer options returned by an LLM."""

    model_config = ConfigDict(extra="forbid")

    A: str
    B: str
    C: str
    D: str


class GeneratedQuestionOutput(BaseModel):
    """Structured generated-question output returned by an LLM."""

    model_config = ConfigDict(extra="forbid")

    prompt: str
    options: QuestionOptionsOutput
    correct_option: Literal["A", "B", "C", "D"]
    source_note: str
    source_url: str
    subcategory: str
    topic: str
    entities: list[str]


@dataclass(frozen=True)
class LLMQuestionGenerator:
    """Generate QOTD candidates using a provider-neutral LLM client."""

    llm_client: LLMClient
    prompt_path: Path = DEFAULT_PROMPT_PATH
    max_output_tokens: int = 1200

    def __call__(
        self,
        topic: QuestionTopic,
        category: str,
        game_date: date,
        rejection_reasons: tuple[str, ...],
        /,
    ) -> GeneratedQuestionCandidate:
        """Generate one structured question candidate from a topic."""

        payload = {
            "game_date": game_date.isoformat(),
            "category": category,
            "topic": {
                "title": topic.title,
                "summary": topic.summary,
                "source_url": topic.source_url,
            },
            "prior_rejection_reasons": list(rejection_reasons),
        }
        data = self.llm_client.create_structured_response(
            prompt_path=self.prompt_path,
            payload=payload,
            response_model=GeneratedQuestionOutput,
            schema_name="qotd_generated_question",
            max_output_tokens=self.max_output_tokens,
        )
        return GeneratedQuestionCandidate(
            question=Question(
                game_date=game_date.isoformat(),
                prompt=data.prompt,
                options=data.options.model_dump(),
                correct_option=data.correct_option,
                source_note=data.source_note,
                source_url=data.source_url,
            ),
            topic_source=topic,
            category=category,
            subcategory=data.subcategory,
            topic=data.topic,
            entities=tuple(data.entities),
        )


@dataclass(frozen=True)
class GenerateQuestionForTopicConfig:
    """Configuration for generating one question from one topic.

    The caller has already chosen the broad category and topic. This use case
    owns candidate generation, structural validation, novelty checks against
    recent QOTD history, and source verification. AI-powered components are
    injected so the orchestration can be tested without live model or web calls.
    """

    game_date: date
    category: str
    topic: QuestionTopic
    state_store: StorageClient
    attempts: int = 2
    novelty_topic_days: int = 30
    novelty_entity_days: int = 14


@dataclass(frozen=True)
class GenerateQuestionForTopicResult:
    """Result of a successful question generation run."""

    candidate: GeneratedQuestionCandidate
    verification: VerificationResult
    rejection_reasons: tuple[str, ...]


class QuestionGenerator(Protocol):
    """Component that generates one question candidate from a topic."""

    def __call__(
        self,
        topic: QuestionTopic,
        category: str,
        game_date: date,
        rejection_reasons: tuple[str, ...],
        /,
    ) -> GeneratedQuestionCandidate:
        """Return one structured question candidate."""


class QuestionVerifier(Protocol):
    """Component that verifies a generated candidate against sources."""

    def __call__(self, candidate: GeneratedQuestionCandidate, /) -> VerificationResult:
        """Return whether the candidate is safe and sourced enough to send."""


def _recent_records(question_records: list[dict[str, Any]], *, game_date: date, days: int) -> list[dict[str, Any]]:
    cutoff = game_date - timedelta(days=days)
    recent_records: list[dict[str, Any]] = []
    for record in question_records:
        try:
            record_date = date.fromisoformat(str(record["game_date"]))
        except (KeyError, TypeError, ValueError):
            continue
        if cutoff <= record_date < game_date:
            recent_records.append(record)
    return recent_records


def check_question_novelty(
    candidate: GeneratedQuestionCandidate,
    question_records: list[dict[str, Any]],
    *,
    game_date: date,
    topic_days: int = 30,
    entity_days: int = 14,
) -> str | None:
    """Return a rejection reason if the candidate repeats recent trivia."""

    topic = candidate.topic.strip().casefold()
    if topic:
        for record in _recent_records(question_records, game_date=game_date, days=topic_days):
            if topic == str(record.get("topic") or "").strip().casefold():
                return f"topic repeated within {topic_days} days: {candidate.topic}"

    entities = {entity.strip().casefold() for entity in candidate.entities if entity.strip()}
    if entities:
        for record in _recent_records(question_records, game_date=game_date, days=entity_days):
            raw_entities = record.get("entities") or ()
            if isinstance(raw_entities, str):
                raw_entities = [raw_entities]
            recent_entities = {str(entity).strip().casefold() for entity in raw_entities if str(entity).strip()}
            repeated = sorted(entities & recent_entities)
            if repeated:
                return f"entity repeated within {entity_days} days: {', '.join(repeated)}"
    return None


def generate_question_for_topic(
    config: GenerateQuestionForTopicConfig,
    *,
    generate_question: QuestionGenerator,
    verify_question: QuestionVerifier,
) -> GenerateQuestionForTopicResult:
    """Generate one verified question for the configured category and topic."""

    if config.attempts < 1:
        raise ValueError("attempts must be at least 1")

    question_records = config.state_store.read_question_records()
    rejection_reasons: list[str] = []
    for attempt_number in range(1, config.attempts + 1):
        try:
            candidate = generate_question(
                config.topic,
                config.category,
                config.game_date,
                tuple(rejection_reasons),
            )
            validate_question(candidate.question)
        except ValueError as exc:
            rejection_reasons.append(f"attempt {attempt_number}: invalid question: {exc}")
            continue

        novelty_reason = check_question_novelty(
            candidate,
            question_records,
            game_date=config.game_date,
            topic_days=config.novelty_topic_days,
            entity_days=config.novelty_entity_days,
        )
        if novelty_reason is not None:
            rejection_reasons.append(f"attempt {attempt_number}: {novelty_reason}")
            continue

        verification = verify_question(candidate)
        if not verification.passed:
            rejection_reasons.append(f"attempt {attempt_number}: verification failed: {verification.reason}")
            continue

        return GenerateQuestionForTopicResult(
            candidate=candidate,
            verification=verification,
            rejection_reasons=tuple(rejection_reasons),
        )

    raise RuntimeError("Could not generate a verified QOTD question for topic")
