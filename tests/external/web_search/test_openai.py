from __future__ import annotations

import json
import unittest
from types import SimpleNamespace
from typing import Any

from qotd.external.web_search.openai import OpenAIWebSearchClient


class FakeResponses:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return SimpleNamespace(
            output_text=json.dumps(
                {
                    "results": [
                        {
                            "title": "Jupiter facts",
                            "url": "https://science.nasa.gov/jupiter/facts/",
                            "snippet": "Jupiter has the Great Red Spot.",
                        }
                    ]
                }
            )
        )


class OpenAIWebSearchClientTests(unittest.TestCase):
    def test_search_uses_web_tool_and_normalizes_structured_results(self) -> None:
        responses = FakeResponses()
        client = OpenAIWebSearchClient(client=SimpleNamespace(responses=responses), model="research-model")

        results = client.search("Jupiter trivia", limit=3)

        self.assertEqual(results[0].title, "Jupiter facts")
        self.assertEqual(results[0].url, "https://science.nasa.gov/jupiter/facts/")
        self.assertEqual(results[0].snippet, "Jupiter has the Great Red Spot.")
        self.assertEqual(responses.calls[0]["tools"], [{"type": "web_search"}])
        self.assertEqual(responses.calls[0]["model"], "research-model")
        self.assertEqual(
            responses.calls[0]["text"]["format"]["schema"]["properties"]["results"]["maxItems"],
            3,
        )


if __name__ == "__main__":
    unittest.main()
