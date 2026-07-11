"""Research, generate, and verify QOTD questions."""

from __future__ import annotations

import random
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Callable, Literal, Protocol
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict

from qotd.domain.categories import QUESTION_CATEGORIES
from qotd.domain.models import Question
from qotd.domain.validation import validate_question
from qotd.external.llm.core import LLMClient
from qotd.external.web_search.core import WebSearchClient, WebSearchResult


DEFAULT_PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "generate_question_for_topic.md"
_VOLATILE_TERMS = re.compile(r"\b(today|currently|current|latest|live|price|ranking|standings?)\b", re.IGNORECASE)


@dataclass(frozen=True)
class QuestionTopic:
    """A researched topic candidate backed by retrieved evidence."""

    title: str
    summary: str
    source_url: str


@dataclass(frozen=True)
class GeneratedQuestionCandidate:
    """A generated question and the metadata needed to audit it."""

    question: Question
    topic_source: QuestionTopic
    category: str
    topic: str
    source_urls: tuple[str, ...]
    source_evidence: tuple[str, ...]


@dataclass(frozen=True)
class ResearchedQuestionResult:
    """Successful end-to-end researched-generation result."""

    candidate: GeneratedQuestionCandidate
    attempts_used: int
    rejection_reasons: tuple[str, ...]


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
    source_urls: list[str]
    topic: str


class QuestionGenerator(Protocol):
    """Generate a question strictly from supplied research evidence."""

    def __call__(
        self,
        topic: QuestionTopic,
        category: str,
        game_date: date,
        evidence: tuple[WebSearchResult, ...],
        rejection_reasons: tuple[str, ...],
        /,
    ) -> GeneratedQuestionCandidate:
        """Return one structured candidate."""


@dataclass(frozen=True)
class LLMQuestionGenerator:
    """Generate structured QOTD candidates with an injected LLM client."""

    llm_client: LLMClient
    prompt_path: Path = DEFAULT_PROMPT_PATH
    max_output_tokens: int = 1200

    def __call__(
        self,
        topic: QuestionTopic,
        category: str,
        game_date: date,
        evidence: tuple[WebSearchResult, ...],
        rejection_reasons: tuple[str, ...],
        /,
    ) -> GeneratedQuestionCandidate:
        """Generate one candidate using only retrieved search evidence."""

        data = self.llm_client.create_structured_response(
            prompt_path=self.prompt_path,
            payload={
                "category": category,
                "topic": {"title": topic.title, "summary": topic.summary},
                "evidence": [
                    {"title": result.title, "url": result.url, "snippet": result.snippet}
                    for result in evidence
                ],
                "prior_rejection_reasons": list(rejection_reasons),
            },
            response_model=GeneratedQuestionOutput,
            schema_name="qotd_generated_question",
            max_output_tokens=self.max_output_tokens,
        )
        evidence_by_url = {result.url: result.snippet for result in evidence}
        return GeneratedQuestionCandidate(
            question=Question(
                game_date=game_date.isoformat(),
                prompt=data.prompt,
                options=data.options.model_dump(),
                correct_option=data.correct_option,
                source_note=data.source_note,
                source_url=data.source_urls[0] if data.source_urls else "",
            ),
            topic_source=topic,
            category=category,
            topic=data.topic,
            source_urls=tuple(data.source_urls),
            source_evidence=tuple(evidence_by_url.get(url, "") for url in data.source_urls),
        )


@dataclass(frozen=True)
class GenerateResearchedQuestionConfig:
    """Configuration for the complete, deliberately small generation flow."""

    game_date: date
    categories: tuple[str, ...] = QUESTION_CATEGORIES
    seed: str | int | None = None
    attempts: int = 3
    search_result_limit: int = 5


@dataclass(frozen=True)
class GenerateQuestionSamplesConfig:
    """Configuration for isolated, topic-driven question sampling."""

    topic: str
    sample_count: int
    game_date: date
    category: str = "General Knowledge"
    search_result_limit: int = 5


FailureAlert = Callable[[str], None]


def generate_question_samples(
    config: GenerateQuestionSamplesConfig,
    *,
    search_client: WebSearchClient,
    generate_question: QuestionGenerator,
) -> tuple[GeneratedQuestionCandidate, ...]:
    """Generate reviewable candidates without sending or persisting them."""

    topic_text = config.topic.strip()
    if not topic_text:
        raise ValueError("topic cannot be blank")
    if config.sample_count < 1:
        raise ValueError("sample count must be at least 1")
    if config.search_result_limit < 1:
        raise ValueError("search result limit must be at least 1")

    evidence = tuple(
        result
        for result in search_client.search(
            f"{topic_text} trivia facts primary authoritative sources",
            limit=config.search_result_limit,
        )
        if _valid_search_result(result)
    )
    if not evidence:
        raise RuntimeError(f"No usable source evidence found for topic: {topic_text}")

    topic = QuestionTopic(
        title=topic_text,
        summary="Research evidence supplied for developer question sampling.",
        source_url=evidence[0].url,
    )
    candidates = []
    for _ in range(config.sample_count):
        candidates.append(
            generate_question(
                topic,
                config.category,
                config.game_date,
                evidence,
                (),
            )
        )
    return tuple(candidates)


def choose_category(categories: tuple[str, ...], *, seed: str | int | None = None) -> str:
    """Choose one configured category, reproducibly when a seed is supplied."""

    cleaned = tuple(category.strip() for category in categories if category.strip())
    if not cleaned:
        raise ValueError("at least one category is required")
    return random.Random(seed).choice(cleaned)


def _valid_search_result(result: WebSearchResult) -> bool:
    parsed = urlparse(result.url)
    return bool(
        result.title.strip()
        and result.snippet.strip()
        and parsed.scheme in {"http", "https"}
        and parsed.netloc
    )


def _authority_score(result: WebSearchResult) -> int:
    host = (urlparse(result.url).hostname or "").casefold()
    return int(host.endswith(".gov")) * 3 + int(host.endswith(".edu")) * 2 + int(host.endswith(".org"))


def discover_topics(
    search_client: WebSearchClient,
    category: str,
    *,
    limit: int,
) -> tuple[WebSearchResult, ...]:
    """Find viable topic evidence, preferring authoritative results."""

    results = search_client.search(
        f"{category} trivia facts primary authoritative sources",
        limit=limit,
    )
    viable = [result for result in results if _valid_search_result(result) and not _VOLATILE_TERMS.search(result.title)]
    return tuple(sorted(viable, key=_authority_score, reverse=True))


def validate_researched_candidate(
    candidate: GeneratedQuestionCandidate,
    evidence: tuple[WebSearchResult, ...],
) -> None:
    """Reject questions not deterministically supported by retrieved evidence."""

    validate_question(candidate.question)
    if not candidate.topic.strip():
        raise ValueError("topic cannot be blank")
    if _VOLATILE_TERMS.search(candidate.question.prompt):
        raise ValueError("question relies on a volatile claim")
    if not candidate.source_urls or len(candidate.source_urls) != len(set(candidate.source_urls)):
        raise ValueError("question must cite one or more distinct source URLs")

    evidence_by_url = {item.url: item.snippet for item in evidence if _valid_search_result(item)}
    if any(url not in evidence_by_url for url in candidate.source_urls):
        raise ValueError("all source URLs must come from retrieved evidence")
    cited_text = " ".join(evidence_by_url[url] for url in candidate.source_urls).casefold()
    if not cited_text.strip():
        raise ValueError("source evidence cannot be blank")

    correct_text = candidate.question.options[candidate.question.correct_option].strip().casefold()
    supported_options = {
        label
        for label, option in candidate.question.options.items()
        if option.strip().casefold() in cited_text
    }
    if candidate.question.correct_option not in supported_options:
        raise ValueError("retrieved evidence does not support the correct answer")
    if len(supported_options) != 1:
        raise ValueError("retrieved evidence supports multiple plausible answers")
    if correct_text in candidate.question.prompt.casefold():
        raise ValueError("question prompt leaks the correct answer")


def generate_researched_question(
    config: GenerateResearchedQuestionConfig,
    *,
    search_client: WebSearchClient,
    generate_question: QuestionGenerator,
    alert_organizer: FailureAlert | None = None,
) -> ResearchedQuestionResult:
    """Choose, research, generate, and verify a question or fail closed."""

    if config.attempts < 1:
        raise ValueError("attempts must be at least 1")
    if config.search_result_limit < 1:
        raise ValueError("search_result_limit must be at least 1")

    seed = config.seed if config.seed is not None else config.game_date.isoformat()
    rng = random.Random(seed)
    category = choose_category(config.categories, seed=seed)
    rejection_reasons: list[str] = []
    for attempt in range(1, config.attempts + 1):
        evidence = discover_topics(search_client, category, limit=config.search_result_limit)
        if not evidence:
            rejection_reasons.append(f"attempt {attempt}: search returned no viable evidence")
            continue
        topic_result = rng.choice(evidence)
        topic = QuestionTopic(topic_result.title, topic_result.snippet, topic_result.url)
        try:
            candidate = generate_question(
                topic,
                category,
                config.game_date,
                evidence,
                tuple(rejection_reasons),
            )
            validate_researched_candidate(candidate, evidence)
        except ValueError as exc:
            rejection_reasons.append(f"attempt {attempt}: {exc}")
            continue
        return ResearchedQuestionResult(candidate, attempt, tuple(rejection_reasons))

    message = "Could not generate a verified QOTD question: " + "; ".join(rejection_reasons)
    if alert_organizer is not None:
        alert_organizer(message)
    raise RuntimeError(message)
