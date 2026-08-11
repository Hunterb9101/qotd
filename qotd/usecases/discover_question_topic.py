"""Discover a QOTD Question topic with web-backed research."""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict

from qotd.domain.models import QuestionTopic
from qotd.external.llm.core import LLMClient
from qotd.external.web_search.core import (
    WebSearchClient,
    WebSearchResult,
    is_valid_web_search_result,
)


DEFAULT_TOPIC_DISCOVERY_PROMPT_PATH = (
    Path(__file__).resolve().parents[1] / "prompts" / "discover_question_topics.md"
)


class DiscoveredTopicOutput(BaseModel):
    """One creative direction proposed for question research."""

    model_config = ConfigDict(extra="forbid")

    title: str
    summary: str


class TopicDiscoveryOutput(BaseModel):
    """Structured collection of proposed question topics."""

    model_config = ConfigDict(extra="forbid")

    topics: list[DiscoveredTopicOutput]


@dataclass(frozen=True)
class DiscoveredWebQuestionTopic:
    """Selected web topic and any retrieved evidence usable for generation."""

    topic: QuestionTopic
    evidence: tuple[WebSearchResult, ...]


@dataclass(frozen=True)
class LLMTopicDiscoverer:
    """Use web search and an editorial prompt to propose topic directions."""

    llm_client: LLMClient
    prompt_path: Path = DEFAULT_TOPIC_DISCOVERY_PROMPT_PATH
    max_output_tokens: int = 12000

    def search(self, query: str, *, limit: int = 5) -> tuple[WebSearchResult, ...]:
        """Return prompt-planned topic directions through the web-search boundary."""

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
            WebSearchResult(title=topic.title, url="", snippet=topic.summary)
            for topic in data.topics[:limit]
        )


def _authority_score(result: WebSearchResult) -> int:
    host = (urlparse(result.url).hostname or "").casefold()
    return int(host.endswith(".gov")) * 3 + int(host.endswith(".edu")) * 2 + int(host.endswith(".org"))


def discover_question_topic_from_web(
    search_client: WebSearchClient,
    *,
    category: str,
    game_date: date,
    lenses: tuple[str, str],
    limit: int,
    seed: str | int,
) -> DiscoveredWebQuestionTopic | None:
    """Select one viable topic direction and retain any source evidence."""

    results = search_client.search(
        f"{category} trivia facts; as of date: {game_date.isoformat()}; "
        f"subject lens: {lenses[0]}; story angle: {lenses[1]}; "
        "surprising approachable topics; timely creative directions",
        limit=limit,
    )
    viable = tuple(result for result in results if result.title.strip() and result.snippet.strip())
    if not viable:
        return None
    ordered = sorted(viable, key=_authority_score, reverse=True)
    selected = random.Random(seed).choice(ordered)
    return DiscoveredWebQuestionTopic(
        topic=QuestionTopic(selected.title, selected.snippet, selected.url, lenses=lenses),
        evidence=tuple(result for result in viable if is_valid_web_search_result(result)),
    )
