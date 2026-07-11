"""OpenAI web-search implementation of the search boundary."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

from qotd.external.web_search.core import WebSearchResult


@dataclass(frozen=True)
class OpenAIWebSearchClient:
    """Use the OpenAI Responses web-search tool and normalize its output."""

    client: Any
    model: str

    def search(self, query: str, *, limit: int = 5) -> tuple[WebSearchResult, ...]:
        """Search the web and return title, URL, and evidence text."""

        response = self.client.responses.create(
            model=self.model,
            tools=[{"type": "web_search"}],
            input=(
                f"Research this trivia topic: {query}\n"
                f"Return JSON with a results array of at most {limit} objects. "
                "Each object must contain title, url, and an evidence snippet. "
                "Prefer primary or authoritative sources."
            ),
            text={
                "format": {
                    "type": "json_schema",
                    "name": "qotd_web_search_results",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "results": {
                                "type": "array",
                                "maxItems": limit,
                                "items": {
                                    "type": "object",
                                    "additionalProperties": False,
                                    "properties": {
                                        "title": {"type": "string"},
                                        "url": {"type": "string"},
                                        "snippet": {"type": "string"},
                                    },
                                    "required": ["title", "url", "snippet"],
                                },
                            }
                        },
                        "required": ["results"],
                    },
                }
            },
        )
        payload = json.loads(response.output_text)
        return tuple(WebSearchResult(**item) for item in payload["results"])


def build_openai_web_search_client(*, model: str, api_key: str | None = None) -> OpenAIWebSearchClient:
    """Build an OpenAI-backed web-search client from explicit or environment config."""

    from openai import OpenAI

    resolved_api_key = api_key or os.environ.get("OPENAI_API_KEY")
    if not resolved_api_key:
        raise ValueError("OPENAI_API_KEY is required for OpenAI web search")
    return OpenAIWebSearchClient(client=OpenAI(api_key=resolved_api_key), model=model)
