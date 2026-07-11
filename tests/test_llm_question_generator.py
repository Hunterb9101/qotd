from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path
from typing import Any, cast

from qotd.usecases.generate_question_for_topic import LLMQuestionGenerator, QuestionTopic


class FakeLLMClient:
    def __init__(self, output: dict[str, Any]) -> None:
        self.output = output
        self.calls: list[dict[str, Any]] = []

    def create_structured_response(
        self,
        *,
        prompt_path: Path,
        payload: dict[str, Any],
        response_model: type[Any],
        schema_name: str,
        max_output_tokens: int,
    ) -> Any:
        self.calls.append(
            {
                "prompt_path": prompt_path,
                "payload": payload,
                "response_model": response_model,
                "schema_name": schema_name,
                "max_output_tokens": max_output_tokens,
            }
        )
        return response_model.model_validate(self.output)


class LLMQuestionGeneratorTests(unittest.TestCase):
    def test_llm_generator_maps_structured_response_to_candidate(self) -> None:
        output: dict[str, Any] = {
            "prompt": "Which state produces the most cheese?",
            "options": {
                "A": "California",
                "B": "New York",
                "C": "Wisconsin",
                "D": "Texas",
            },
            "correct_option": "C",
            "source_note": "USDA data identifies Wisconsin as the top cheese-producing state.",
            "source_url": "https://example.com/cheese-production",
            "subcategory": "Cheese",
            "topic": "U.S. cheese production",
            "entities": ["Wisconsin", "USDA"],
        }
        client = FakeLLMClient(output)
        with tempfile.TemporaryDirectory() as temp_dir:
            prompt_path = Path(temp_dir) / "prompt.md"
            prompt_path.write_text("Generate a question.", encoding="utf-8")

            generator = LLMQuestionGenerator(
                llm_client=client,
                prompt_path=prompt_path,
            )
            topic = QuestionTopic(
                title="National Cheddar Day",
                summary="A food holiday.",
                source_url="https://example.com/cheddar-day",
            )

            candidate = generator(topic, "Food & Drink", date(2026, 7, 10), ("previous failure",))

        self.assertEqual(candidate.question.prompt, "Which state produces the most cheese?")
        self.assertEqual(candidate.question.options["C"], "Wisconsin")
        self.assertEqual(candidate.question.correct_option, "C")
        self.assertEqual(candidate.topic_source, topic)
        self.assertEqual(candidate.category, "Food & Drink")
        self.assertEqual(candidate.subcategory, "Cheese")
        self.assertEqual(candidate.entities, ("Wisconsin", "USDA"))

        call = client.calls[0]
        self.assertEqual(call["prompt_path"], prompt_path)
        self.assertEqual(call["schema_name"], "qotd_generated_question")
        request_payload = cast(dict[str, Any], call["payload"])
        self.assertEqual(request_payload["category"], "Food & Drink")
        self.assertEqual(request_payload["topic"]["title"], "National Cheddar Day")
        self.assertEqual(request_payload["prior_rejection_reasons"], ["previous failure"])


if __name__ == "__main__":
    unittest.main()
