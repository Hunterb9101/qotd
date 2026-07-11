"""Provider-neutral web-search contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class WebSearchResult:
    """One web-search result containing evidence usable for research."""

    title: str
    url: str
    snippet: str


class WebSearchClient(Protocol):
    """Search provider used by researched question generation."""

    def search(self, query: str, *, limit: int = 5) -> tuple[WebSearchResult, ...]:
        """Return deterministic, provider-normalized search results."""
