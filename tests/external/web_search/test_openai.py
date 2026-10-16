from __future__ import annotations

import json
import unittest
from types import SimpleNamespace
from typing import Any

from qotd.external.web_search.openai import OpenAIWebSearchClient
from qotd.external.storage.memory import InMemoryAdapter


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
            ),
            usage=SimpleNamespace(
                input_tokens=2_000,
                output_tokens=1_000,
                total_tokens=3_000,
                input_tokens_details=SimpleNamespace(cached_tokens=500),
            ),
            output=[SimpleNamespace(type="web_search_call")],
        )


class OpenAIWebSearchClientTests(unittest.TestCase):
    def test_search_uses_web_tool_and_normalizes_structured_results(self) -> None:
        responses = FakeResponses()
        state = InMemoryAdapter()
        client = OpenAIWebSearchClient(
            client=SimpleNamespace(responses=responses),
            model="gpt-5.4-mini",
            state=state,
            use_case="publish_question",
            usecase_run_id="publish-run",
        )

        results = client.search("Jupiter trivia", limit=3)

        self.assertEqual(results[0].title, "Jupiter facts")
        self.assertEqual(results[0].url, "https://science.nasa.gov/jupiter/facts/")
        self.assertEqual(results[0].snippet, "Jupiter has the Great Red Spot.")
        self.assertEqual(responses.calls[0]["tools"], [{"type": "web_search"}])
        self.assertEqual(responses.calls[0]["model"], "gpt-5.4-mini")
        self.assertEqual(
            responses.calls[0]["text"]["format"]["schema"]["properties"]["results"]["maxItems"],
            3,
        )
        ai_call = next(iter(state.ai_calls.values()))
        self.assertEqual(ai_call.use_case, "publish_question")
        self.assertEqual(ai_call.usecase_run_id, "publish-run")
        self.assertEqual(ai_call.input_tokens, 2_000)
        self.assertEqual(ai_call.cached_input_tokens, 500)
        self.assertEqual(ai_call.output_tokens, 1_000)
        self.assertEqual(ai_call.web_search_calls, 1)


if __name__ == "__main__":
    unittest.main()
