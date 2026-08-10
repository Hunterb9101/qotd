from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, ValidationError

from qotd.external.llm.openai import OpenAILLMClient, render_prompt
from qotd.usecases.repair_question import RepairedQuestionOutput


class ExampleOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    option: Literal["A", "B"]


class FakeResponses:
    def __init__(self, output: dict[str, Any]) -> None:
        self.output = output
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(kwargs)
        return SimpleNamespace(output_text=json.dumps(self.output))


class FakeOpenAIClient:
    def __init__(self, output: dict[str, Any]) -> None:
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

    def test_create_structured_response_uses_pydantic_schema(self) -> None:
        client = FakeOpenAIClient({"option": "A"})
        with tempfile.TemporaryDirectory() as temp_dir:
            prompt_path = Path(temp_dir) / "prompt.md"
            prompt_path.write_text("Return JSON.", encoding="utf-8")

            result = OpenAILLMClient(client=client, model="test-model").create_structured_response(
                prompt_path=prompt_path,
                payload={"reply": "A"},
                response_model=ExampleOutput,
                schema_name="example_output",
                max_output_tokens=50,
            )

        self.assertEqual(result.option, "A")
        call = client.responses.calls[0]
        self.assertEqual(call["instructions"], "Return JSON.")
        self.assertEqual(call["input"], "Return the requested structured result.")
        self.assertNotIn("tools", call)
        text_config = cast(dict[str, Any], call["text"])
        self.assertEqual(text_config["format"]["name"], "example_output")
        self.assertIn("option", text_config["format"]["schema"]["properties"])

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

            OpenAILLMClient(client=client, model="test-model").create_structured_response(
                prompt_path=prompt_path,
                payload={},
                response_model=RepairedQuestionOutput,
                schema_name="qotd_repaired_question",
                max_output_tokens=50,
            )

        schema = client.responses.calls[0]["text"]["format"]["schema"]
        self.assertNotIn("propertyNames", json.dumps(schema))

    def test_create_structured_response_can_enable_web_search(self) -> None:
        client = FakeOpenAIClient({"option": "A"})
        with tempfile.TemporaryDirectory() as temp_dir:
            prompt_path = Path(temp_dir) / "prompt.md"
            prompt_path.write_text("Research and return JSON.", encoding="utf-8")

            OpenAILLMClient(client=client, model="test-model").create_structured_response(
                prompt_path=prompt_path,
                payload={},
                response_model=ExampleOutput,
                schema_name="example_output",
                max_output_tokens=50,
                tools=({"type": "web_search"},),
            )

        self.assertEqual(client.responses.calls[0]["tools"], [{"type": "web_search"}])

    def test_create_structured_response_rejects_invalid_model_output(self) -> None:
        client = FakeOpenAIClient({"option": "C"})
        with tempfile.TemporaryDirectory() as temp_dir:
            prompt_path = Path(temp_dir) / "prompt.md"
            prompt_path.write_text("Return JSON.", encoding="utf-8")

            with self.assertRaises(ValidationError):
                OpenAILLMClient(client=client, model="test-model").create_structured_response(
                    prompt_path=prompt_path,
                    payload={},
                    response_model=ExampleOutput,
                    schema_name="example_output",
                    max_output_tokens=50,
                )


if __name__ == "__main__":
    unittest.main()
