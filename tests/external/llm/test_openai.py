from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, ValidationError

from qotd.external.llm.openai import OpenAILLMClient, render_prompt
from qotd.usecases.repair_question import DEFAULT_REPAIR_PROMPT_PATH, RepairedQuestionOutput
from qotd.external.storage.memory import InMemoryAdapter


class ExampleOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    option: Literal["A", "B"]


class FakeResponses:
    def __init__(self, output: dict[str, Any] | Exception) -> None:
        self.output = output
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(kwargs)
        if isinstance(self.output, Exception):
            raise self.output
        return SimpleNamespace(output_text=json.dumps(self.output))


class FakeOpenAIClient:
    def __init__(self, output: dict[str, Any] | Exception) -> None:
        self.responses = FakeResponses(output)


class OpenAILLMClientTests(unittest.TestCase):
    def test_render_prompt_replaces_nested_values_and_loops(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            prompt_path = Path(temp_dir) / "prompt.md"
            prompt_path.write_text(
                "Topic: {{ topic.title }}\n{% for option in options %}{{ option }} {% endfor %}",
                encoding="utf-8",
            )

            rendered = render_prompt(
                prompt_path,
                {"topic": {"title": "Jupiter"}, "options": ["A", "B", "C", "D"]},
            )

        self.assertEqual(rendered, "Topic: Jupiter\nA B C D ")

    def test_repair_prompt_requires_rewriting_an_answer_leak(self) -> None:
        rendered = render_prompt(
            DEFAULT_REPAIR_PROMPT_PATH,
            {
                "category": "Food",
                "topic": "Cheese production",
                "question": {
                    "prompt": "Why is Wisconsin the biggest cheese producer?",
                    "options": {"A": "California", "B": "New York", "C": "Wisconsin", "D": "Texas"},
                    "correct_option": "C",
                    "correct_answer": "Wisconsin",
                    "source_note": "USDA data",
                },
                "sources": [{"url": "https://example.com", "evidence": "Wisconsin produces the most cheese."}],
                "issues": ["question prompt leaks the correct answer"],
            },
        )

        self.assertIn("rewrite the Player-facing prompt", rendered)
        self.assertIn("Returning\n  the original prompt is invalid", rendered)
        self.assertIn("case-insensitive match", rendered)

    def test_create_structured_response_uses_pydantic_schema(self) -> None:
        client = FakeOpenAIClient({"option": "A"})
        state = InMemoryAdapter()
        with tempfile.TemporaryDirectory() as temp_dir:
            prompt_path = Path(temp_dir) / "prompt.md"
            prompt_path.write_text("Return JSON.", encoding="utf-8")

            result = OpenAILLMClient(client=client, model="test-model", state=state).create_structured_response(
                prompt_path=prompt_path,
                payload={"reply": "A"},
                response_model=ExampleOutput,
                schema_name="example_output",
                max_output_tokens=50,
                use_case="score_responses",
                usecase_run_id="score-run",
            )

        self.assertEqual(result.option, "A")
        call = client.responses.calls[0]
        self.assertEqual(call["instructions"], "Return JSON.")
        self.assertEqual(call["input"], "Return the requested structured result.")
        self.assertNotIn("tools", call)
        text_config = cast(dict[str, Any], call["text"])
        self.assertEqual(text_config["format"]["name"], "example_output")
        self.assertIn("option", text_config["format"]["schema"]["properties"])
        ai_call = next(iter(state.ai_calls.values()))
        self.assertEqual(ai_call.use_case, "score_responses")
        self.assertEqual(ai_call.prompt, "prompt")
        self.assertEqual(ai_call.usecase_run_id, "score-run")
        self.assertEqual(ai_call.request, call)
        self.assertEqual(ai_call.response, {"output_text": '{"option": "A"}'})
        self.assertEqual(ai_call.status, "succeeded")
        self.assertEqual(ai_call.provider, "openai")
        self.assertEqual(ai_call.model, "test-model")
        self.assertIsNotNone(ai_call.latency_ms)

    def test_repaired_question_schema_avoids_unsupported_property_names(self) -> None:
        client = FakeOpenAIClient(
            {
                "prompt": "Which planet is known as the Red Planet?",
                "options": {"A": "Mars", "B": "Venus", "C": "Jupiter", "D": "Mercury"},
                "correct_option": "A",
                "source_note": "NASA",
            }
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            prompt_path = Path(temp_dir) / "prompt.md"
            prompt_path.write_text("Return JSON.", encoding="utf-8")

            OpenAILLMClient(client=client, model="test-model", state=InMemoryAdapter()).create_structured_response(
                prompt_path=prompt_path,
                payload={},
                response_model=RepairedQuestionOutput,
                schema_name="qotd_repaired_question",
                max_output_tokens=50,
                use_case="publish_question",
                usecase_run_id="publish-run",
            )

        schema = client.responses.calls[0]["text"]["format"]["schema"]
        self.assertNotIn("propertyNames", json.dumps(schema))

    def test_create_structured_response_can_enable_web_search(self) -> None:
        client = FakeOpenAIClient({"option": "A"})
        with tempfile.TemporaryDirectory() as temp_dir:
            prompt_path = Path(temp_dir) / "prompt.md"
            prompt_path.write_text("Research and return JSON.", encoding="utf-8")

            OpenAILLMClient(client=client, model="test-model", state=InMemoryAdapter()).create_structured_response(
                prompt_path=prompt_path,
                payload={},
                response_model=ExampleOutput,
                schema_name="example_output",
                max_output_tokens=50,
                tools=({"type": "web_search"},),
                use_case="publish_question",
                usecase_run_id="publish-run",
            )

        self.assertEqual(client.responses.calls[0]["tools"], [{"type": "web_search"}])

    def test_create_structured_response_rejects_invalid_model_output(self) -> None:
        client = FakeOpenAIClient({"option": "C"})
        with tempfile.TemporaryDirectory() as temp_dir:
            prompt_path = Path(temp_dir) / "prompt.md"
            prompt_path.write_text("Return JSON.", encoding="utf-8")

            with self.assertRaises(ValidationError):
                OpenAILLMClient(client=client, model="test-model", state=InMemoryAdapter()).create_structured_response(
                    prompt_path=prompt_path,
                    payload={},
                    response_model=ExampleOutput,
                    schema_name="example_output",
                    max_output_tokens=50,
                    use_case="publish_question",
                    usecase_run_id="publish-run",
                )

    def test_create_structured_response_records_provider_failure(self) -> None:
        state = InMemoryAdapter()
        client = FakeOpenAIClient(RuntimeError("provider unavailable"))
        with tempfile.TemporaryDirectory() as temp_dir:
            prompt_path = Path(temp_dir) / "prompt.md"
            prompt_path.write_text("Return JSON.", encoding="utf-8")

            with self.assertRaisesRegex(RuntimeError, "provider unavailable"):
                OpenAILLMClient(client=client, model="test-model", state=state).create_structured_response(
                    prompt_path=prompt_path,
                    payload={},
                    response_model=ExampleOutput,
                    schema_name="example_output",
                    max_output_tokens=50,
                    use_case="score_responses",
                    usecase_run_id="failed-score-run",
                )

        ai_call = next(iter(state.ai_calls.values()))
        self.assertEqual(ai_call.status, "failed")
        self.assertEqual(ai_call.error_type, "RuntimeError")
        self.assertEqual(ai_call.error_message, "provider unavailable")
        self.assertIsNone(ai_call.response)


if __name__ == "__main__":
    unittest.main()
