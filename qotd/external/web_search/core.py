"""Provider-neutral web-search contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlparse


@dataclass(frozen=True)
class WebSearchResult:
    """One web-search result containing evidence usable for research."""

    title: str
    url: str
    snippet: str


def is_valid_web_search_result(result: WebSearchResult) -> bool:
    """Return whether a result contains usable HTTP(S) evidence."""

    parsed = urlparse(result.url)
    return bool(
        result.title.strip()
        and result.snippet.strip()
        and parsed.scheme in {"http", "https"}
        and parsed.netloc
    )


class WebSearchClient(Protocol):
    """Search provider used by researched question generation."""

    def search(self, query: str, *, limit: int = 5) -> tuple[WebSearchResult, ...]:
        """Return deterministic, provider-normalized search results."""
