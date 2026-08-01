"""Research, generate, and verify QOTD questions."""

from __future__ import annotations

import random
import re
from dataclasses import dataclass
from datetime import date
from itertools import product
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
DEFAULT_REPAIR_PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "repair_generated_question.md"
DEFAULT_EVALUATION_PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "evaluate_generated_question.md"
DEFAULT_TOPIC_DISCOVERY_PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "discover_question_topics.md"
QUESTION_SUBJECT_LENSES = (
    "people, personalities, and celebrity",
    "everyday life, habits, and social customs",
    "traditions, celebrations, and rituals",
    "pop culture, entertainment, and media appearances",
    "fans, communities, and subcultures",
    "language, slang, nicknames, and catchphrases",
    "fashion, design, symbols, and visual identity",
    "food, drink, and leisure",
    "places, local identity, and regional differences",
    "objects, tools, and technology",
    "making things and behind-the-scenes processes",
    "money, brands, advertising, and trade",
)
QUESTION_STORY_ANGLES = (
    "a surprising origin or evolution",
    "accidents and unintended consequences",
    "rivalries and conflicts",
    "myths, misconceptions, and false memories",
    "an unusual exception or quirky rule",
    "overlooked contributors",
    "adaptation, reinvention, or a comeback",
    "a crossover between different cultures or fields",
    "a rise, decline, or unexpected revival",
    "an oddly specific anecdote with a memorable payoff",
)
_VOLATILE_TERMS = re.compile(r"\b(today|currently|current|latest|live|price|ranking|standings?)\b", re.IGNORECASE)


@dataclass(frozen=True)
class QuestionTopic:
    """A researched topic candidate backed by retrieved evidence."""

    title: str
    summary: str
    source_url: str
    lenses: tuple[str, ...] = ()


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


class GeneratedSourceOutput(BaseModel):
    """One source and the evidence it contributes to a generated question."""

    model_config = ConfigDict(extra="forbid")

    url: str
    evidence: str


class GeneratedQuestionOutput(BaseModel):
    """Structured generated-question output returned by an LLM."""

    model_config = ConfigDict(extra="forbid")

    prompt: str
    options: QuestionOptionsOutput
    correct_option: Literal["A", "B", "C", "D"]
    source_note: str
    sources: list[GeneratedSourceOutput]
    topic: str


class RepairedQuestionOutput(BaseModel):
    """Structured question fields returned by the focused repair pass."""

    model_config = ConfigDict(extra="forbid")

    prompt: str
    options: QuestionOptionsOutput
    correct_option: Literal["A", "B", "C", "D"]
    source_note: str


class QuestionQualityReviewOutput(BaseModel):
    """Structured quality review returned by an LLM evaluator."""

    model_config = ConfigDict(extra="forbid")

    approved: bool
    rejection_reasons: list[str]


class DiscoveredTopicOutput(BaseModel):
    """One volatile creative direction proposed for question research."""

    model_config = ConfigDict(extra="forbid")

    title: str
    summary: str


class TopicDiscoveryOutput(BaseModel):
    """Structured collection of proposed question topics."""

    model_config = ConfigDict(extra="forbid")

    topics: list[DiscoveredTopicOutput]


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


class QuestionEvaluator(Protocol):
    """Evaluate whether a generated question is fair and does not leak its answer."""

    def __call__(self, candidate: GeneratedQuestionCandidate, /) -> tuple[str, ...]:
        """Return actionable rejection reasons, or an empty tuple when approved."""


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
class LLMQuestionGenerator:
    """Generate structured QOTD candidates with an injected LLM client."""

    llm_client: LLMClient
    prompt_path: Path = DEFAULT_PROMPT_PATH
    max_output_tokens: int = 24000
    use_web_search: bool = False

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
                "lenses": list(topic.lenses),
                "evidence": [
                    {"title": result.title, "url": result.url, "snippet": result.snippet}
                    for result in evidence
                ],
                "prior_rejection_reasons": list(rejection_reasons),
            },
            response_model=GeneratedQuestionOutput,
            schema_name="qotd_generated_question",
            max_output_tokens=self.max_output_tokens,
            tools=({"type": "web_search"},) if self.use_web_search else (),
        )
        evidence_by_url = {result.url: result.snippet for result in evidence}
        source_urls = tuple(source.url for source in data.sources)
        source_evidence = tuple(
            evidence_by_url.get(source.url, source.evidence) for source in data.sources
        )
        return GeneratedQuestionCandidate(
            question=Question(
                game_date=game_date.isoformat(),
                prompt=data.prompt,
                options=data.options.model_dump(),
                correct_option=data.correct_option,
                source_note=data.source_note,
                source_url=source_urls[0] if source_urls else "",
            ),
            topic_source=topic,
            category=category,
            topic=data.topic,
            source_urls=source_urls,
            source_evidence=source_evidence,
        )


@dataclass(frozen=True)
class LLMQuestionRepairer:
    """Repair a candidate while preserving its research and creative direction."""

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
        return GeneratedQuestionCandidate(
            question=Question(
                game_date=question.game_date,
                prompt=data.prompt,
                options=data.options.model_dump(),
                correct_option=data.correct_option,
                source_note=data.source_note,
                source_url=question.source_url,
            ),
            topic_source=candidate.topic_source,
            category=candidate.category,
            topic=candidate.topic,
            source_urls=candidate.source_urls,
            source_evidence=candidate.source_evidence,
        )


@dataclass(frozen=True)
class LLMQuestionEvaluator:
    """Use an LLM to reject answer leakage and semantically unfair questions."""

    llm_client: LLMClient
    prompt_path: Path = DEFAULT_EVALUATION_PROMPT_PATH
    max_output_tokens: int = 4000

    def __call__(self, candidate: GeneratedQuestionCandidate, /) -> tuple[str, ...]:
        """Return concise, actionable reasons when a candidate should be regenerated."""

        question = candidate.question
        data = self.llm_client.create_structured_response(
            prompt_path=self.prompt_path,
            payload={
                "category": candidate.category,
                "topic": candidate.topic_source.title,
                "question": {
                    "prompt": question.prompt,
                    "options": question.options,
                    "correct_option": question.correct_option,
                    "correct_answer": question.options[question.correct_option],
                },
                "source_note": question.source_note,
                "source_evidence": list(candidate.source_evidence),
            },
            response_model=QuestionQualityReviewOutput,
            schema_name="qotd_question_quality_review",
            max_output_tokens=self.max_output_tokens,
        )
        reasons = tuple(reason.strip() for reason in data.rejection_reasons if reason.strip())
        if data.approved:
            return ()
        return reasons or ("LLM evaluator rejected the question without a specific reason",)


@dataclass(frozen=True)
class LLMTopicDiscoverer:
    """Use web search and an editorial prompt to propose concrete topic entities."""

    llm_client: LLMClient
    prompt_path: Path = DEFAULT_TOPIC_DISCOVERY_PROMPT_PATH
    max_output_tokens: int = 12000

    def search(self, query: str, *, limit: int = 5) -> tuple[WebSearchResult, ...]:
        """Return prompt-planned topic entities through the web-search boundary."""

        if limit < 1:
            raise ValueError("topic discovery limit must be at least 1")
        data = self.llm_client.create_structured_response(
            prompt_path=self.prompt_path,
            payload={"brief": query, "limit": limit},
            response_model=TopicDiscoveryOutput,
            schema_name="qotd_topic_discovery",
            max_output_tokens=self.max_output_tokens,
            tools=({"type": "web_search"},),
        )
        return tuple(
            WebSearchResult(
                title=topic.title,
                url="",
                snippet=topic.summary,
            )
            for topic in data.topics[:limit]
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
    category: str | None = None
    seed: str | int | None = None
    categories: tuple[str, ...] = QUESTION_CATEGORIES
    attempts: int = 3


FailureAlert = Callable[[str], None]
CandidateValidator = Callable[[GeneratedQuestionCandidate], None]


def _candidate_issues(
    candidate: GeneratedQuestionCandidate,
    *,
    validate_candidate: CandidateValidator,
    evaluate_question: QuestionEvaluator | None,
) -> tuple[str, ...]:
    """Return the concrete issues that a focused repair pass must address."""

    try:
        validate_candidate(candidate)
    except ValueError as exc:
        return (str(exc),)
    if evaluate_question is None:
        return ()
    return evaluate_question(candidate)


def _rejection_summary(attempt: int, issues: tuple[str, ...]) -> str:
    """Build a concise diagnostic for logs and terminal failure messages."""

    return f"attempt {attempt}: " + "; ".join(issues)


def generate_question_samples(
    config: GenerateQuestionSamplesConfig,
    *,
    generate_question: QuestionGenerator,
    repair_question: QuestionRepairer | None = None,
    evaluate_question: QuestionEvaluator | None = None,
) -> tuple[GeneratedQuestionCandidate, ...]:
    """Generate reviewable candidates without sending or persisting them."""

    topic_text = config.topic.strip()
    if not topic_text:
        raise ValueError("topic cannot be blank")
    if config.sample_count < 1:
        raise ValueError("sample count must be at least 1")
    if config.attempts < 1:
        raise ValueError("attempts must be at least 1")
    lens_pairs = choose_lens_pairs(config.sample_count, seed=config.seed)
    categories = (
        (config.category,) * config.sample_count
        if config.category is not None
        else choose_categories(config.sample_count, config.categories, seed=config.seed)
    )
    candidates = []
    for lenses, category in zip(lens_pairs, categories, strict=True):
        topic = QuestionTopic(
            title=topic_text,
            summary="Research this topic with web search before writing the question.",
            source_url="",
            lenses=lenses,
        )
        rejection_reasons: list[str] = []
        candidate: GeneratedQuestionCandidate | None = None
        issues: tuple[str, ...] = ()
        for attempt in range(1, config.attempts + 1):
            try:
                if candidate is not None and repair_question is not None:
                    candidate = repair_question(candidate, issues)
                else:
                    candidate = generate_question(
                        topic,
                        category,
                        config.game_date,
                        (),
                        tuple(rejection_reasons),
                    )
            except ValueError as exc:
                issues = (str(exc),)
                rejection_reasons.append(_rejection_summary(attempt, issues))
                candidate = None
                continue
            issues = _candidate_issues(
                candidate,
                validate_candidate=lambda item: validate_question(item.question),
                evaluate_question=evaluate_question,
            )
            if issues:
                rejection_reasons.append(_rejection_summary(attempt, issues))
                if repair_question is None:
                    candidate = None
                continue
            candidates.append(candidate)
            break
        else:
            raise RuntimeError(
                f"Could not generate a valid sample for lenses {lenses}: " + "; ".join(rejection_reasons)
            )
    return tuple(candidates)


def choose_lens_pairs(count: int, *, seed: str | int | None = None) -> tuple[tuple[str, str], ...]:
    """Choose distinct creative-lens pairs for a batch of candidates."""

    if count < 1:
        raise ValueError("lens pair count must be at least 1")
    pairs = list(product(QUESTION_SUBJECT_LENSES, QUESTION_STORY_ANGLES))
    rng = random.Random(seed)
    rng.shuffle(pairs)
    return tuple(pairs[index % len(pairs)] for index in range(count))


def choose_categories(
    count: int,
    categories: tuple[str, ...] = QUESTION_CATEGORIES,
    *,
    seed: str | int | None = None,
) -> tuple[str, ...]:
    """Choose shuffled categories, avoiding repeats until the set is exhausted."""

    if count < 1:
        raise ValueError("category count must be at least 1")
    cleaned = tuple(category.strip() for category in categories if category.strip())
    if not cleaned:
        raise ValueError("at least one category is required")
    shuffled = list(cleaned)
    random.Random(seed).shuffle(shuffled)
    return tuple(shuffled[index % len(shuffled)] for index in range(count))


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


def _valid_topic_direction(result: WebSearchResult) -> bool:
    """Return whether discovery produced a usable title and creative direction."""

    return bool(result.title.strip() and result.snippet.strip())


def discover_topics(
    search_client: WebSearchClient,
    category: str,
    *,
    limit: int,
    lenses: tuple[str, str] | None = None,
    as_of_date: date | None = None,
) -> tuple[WebSearchResult, ...]:
    """Find viable topic directions, preferring authoritative evidence when present."""

    lens_guidance = ""
    if lenses is not None:
        lens_guidance = f" subject lens: {lenses[0]}; story angle: {lenses[1]};"
    date_guidance = f" as of date: {as_of_date.isoformat()};" if as_of_date is not None else ""
    results = search_client.search(
        f"{category} trivia facts;{date_guidance}{lens_guidance} surprising approachable topics; "
        "timely creative directions",
        limit=limit,
    )
    viable = [result for result in results if _valid_topic_direction(result)]
    return tuple(sorted(viable, key=_authority_score, reverse=True))


def validate_self_researched_candidate(candidate: GeneratedQuestionCandidate) -> None:
    """Validate a candidate whose generator performed its own web research."""

    validate_question(candidate.question)
    if not candidate.topic.strip():
        raise ValueError("topic cannot be blank")
    if _VOLATILE_TERMS.search(candidate.question.prompt):
        raise ValueError("question relies on a volatile claim")
    if not candidate.source_urls or len(candidate.source_urls) != len(set(candidate.source_urls)):
        raise ValueError("question must cite one or more distinct source URLs")
    if len(candidate.source_urls) != len(candidate.source_evidence):
        raise ValueError("each source URL must have supporting evidence")
    if any(not _valid_search_result(WebSearchResult("source", url, evidence)) for url, evidence in zip(
        candidate.source_urls,
        candidate.source_evidence,
        strict=True,
    )):
        raise ValueError("generated source evidence must include valid URLs and nonblank excerpts")

    cited_text = " ".join(candidate.source_evidence).casefold()
    correct_text = candidate.question.options[candidate.question.correct_option].strip().casefold()
    supported_options = {
        label
        for label, option in candidate.question.options.items()
        if option.strip().casefold() in cited_text
    }
    if candidate.question.correct_option not in supported_options:
        raise ValueError("generated source evidence does not support the correct answer")
    if len(supported_options) != 1:
        raise ValueError("generated source evidence supports multiple plausible answers")
    if correct_text in candidate.question.prompt.casefold():
        raise ValueError("question prompt leaks the correct answer")


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
    repair_question: QuestionRepairer | None = None,
    evaluate_question: QuestionEvaluator | None = None,
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
    lenses = choose_lens_pairs(1, seed=seed)[0]
    rejection_reasons: list[str] = []
    candidate: GeneratedQuestionCandidate | None = None
    research_evidence: tuple[WebSearchResult, ...] = ()
    issues: tuple[str, ...] = ()
    for attempt in range(1, config.attempts + 1):
        try:
            if candidate is not None and repair_question is not None:
                candidate = repair_question(candidate, issues)
            else:
                evidence = discover_topics(
                    search_client,
                    category,
                    limit=config.search_result_limit,
                    lenses=lenses,
                    as_of_date=config.game_date,
                )
                if not evidence:
                    issues = ("search returned no viable evidence",)
                    rejection_reasons.append(_rejection_summary(attempt, issues))
                    continue
                topic_result = rng.choice(evidence)
                topic = QuestionTopic(
                    topic_result.title,
                    topic_result.snippet,
                    topic_result.url,
                    lenses=lenses,
                )
                research_evidence = tuple(item for item in evidence if _valid_search_result(item))
                candidate = generate_question(
                    topic,
                    category,
                    config.game_date,
                    research_evidence,
                    tuple(rejection_reasons),
                )
        except ValueError as exc:
            issues = (str(exc),)
            rejection_reasons.append(_rejection_summary(attempt, issues))
            candidate = None
            continue
        validator: CandidateValidator
        if research_evidence:
            def validate_with_research(item: GeneratedQuestionCandidate) -> None:
                validate_researched_candidate(item, research_evidence)

            validator = validate_with_research
        else:
            validator = validate_self_researched_candidate
        issues = _candidate_issues(
            candidate,
            validate_candidate=validator,
            evaluate_question=evaluate_question,
        )
        if issues:
            rejection_reasons.append(_rejection_summary(attempt, issues))
            if repair_question is None:
                candidate = None
            continue
        return ResearchedQuestionResult(candidate, attempt, tuple(rejection_reasons))

    message = "Could not generate a verified QOTD question: " + "; ".join(rejection_reasons)
    if alert_organizer is not None:
        alert_organizer(message)
    raise RuntimeError(message)
