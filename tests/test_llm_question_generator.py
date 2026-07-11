from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path
from typing import Any, cast

from qotd.external.llm.openai import render_prompt
from qotd.external.web_search.core import WebSearchResult
from qotd.usecases.generate_question_for_topic import (
    DEFAULT_PROMPT_PATH,
    GenerateQuestionSamplesConfig,
    LLMQuestionGenerator,
    QuestionGenerator,
    QuestionTopic,
    generate_question_samples,
)


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


class FakeSearchClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []

    def search(self, query: str, *, limit: int = 5) -> tuple[WebSearchResult, ...]:
        self.calls.append((query, limit))
        return (
            WebSearchResult(
                title="Cheese data",
                url="https://example.com/cheese-production",
                snippet="Wisconsin produces the most cheese.",
            ),
        )


class LLMQuestionGeneratorTests(unittest.TestCase):
    def test_generate_samples_uses_supplied_topic_and_requested_count(self) -> None:
        search = FakeSearchClient()
        calls: list[tuple[QuestionTopic, str]] = []

        def generate(topic, category, game_date, evidence, rejection_reasons):
            calls.append((topic, category))
            return LLMQuestionGenerator(FakeLLMClient({
                "prompt": "Which state produces the most cheese?",
                "options": {"A": "California", "B": "New York", "C": "Wisconsin", "D": "Texas"},
                "correct_option": "C",
                "source_note": "USDA cheese production data.",
                "source_urls": ["https://example.com/cheese-production"],
                "topic": "U.S. cheese production",
            }))(topic, category, game_date, evidence, rejection_reasons)

        candidates = generate_question_samples(
            GenerateQuestionSamplesConfig(
                topic="Cheese history",
                sample_count=3,
                game_date=date(2026, 7, 11),
            ),
            search_client=search,
            generate_question=generate,
        )

        self.assertEqual(len(candidates), 3)
        self.assertEqual(len(calls), 3)
        self.assertEqual(calls[0][0].title, "Cheese history")
        self.assertIn("Cheese history", search.calls[0][0])

    def test_generate_samples_validates_topic_and_count(self) -> None:
        with self.assertRaisesRegex(ValueError, "topic cannot be blank"):
            generate_question_samples(
                GenerateQuestionSamplesConfig("  ", 1, date(2026, 7, 11)),
                search_client=FakeSearchClient(),
                generate_question=cast(QuestionGenerator, lambda *args: None),
            )
        with self.assertRaisesRegex(ValueError, "sample count must be at least 1"):
            generate_question_samples(
                GenerateQuestionSamplesConfig("cheese", 0, date(2026, 7, 11)),
                search_client=FakeSearchClient(),
                generate_question=cast(QuestionGenerator, lambda *args: None),
            )
    def test_default_prompt_is_packaged_and_contains_generation_guidance(self) -> None:
        prompt = DEFAULT_PROMPT_PATH.read_text(encoding="utf-8")

        self.assertIn("exactly four distinct options labeled A, B, C, and D", prompt)
        self.assertIn("exactly one option is correct", prompt)
        self.assertIn("supplied source evidence supports that answer", prompt)
        self.assertIn("informal, conversational, and human", prompt)
        self.assertIn("accessible-to-moderate difficulty", prompt)
        self.assertIn("what is surprising, strange, or amusing", prompt)
        self.assertIn("academic, institutional, encyclopedic, or promotional", prompt)
        self.assertIn("sender's personality remain visible", prompt)
        self.assertIn("grim, partisan, medical, legal, or highly volatile", prompt)
        self.assertIn("Do not reveal or strongly hint", prompt)
        self.assertNotIn("Cody", prompt)
        self.assertNotIn("docs/prompts", str(DEFAULT_PROMPT_PATH))

    def test_default_prompt_renders_topic_category_and_evidence(self) -> None:
        rendered = render_prompt(
            DEFAULT_PROMPT_PATH,
            {
                "category": "Food & Drink",
                "topic": {
                    "title": "National Cheddar Day",
                    "summary": "A food holiday.",
                },
                "evidence": [
                    {
                        "title": "USDA cheese data",
                        "url": "https://example.com/cheese-production",
                        "snippet": "Wisconsin produces the most cheese.",
                    }
                ],
                "prior_rejection_reasons": ["The first answer was ambiguous."],
            },
        )

        self.assertIn("Category: Food & Drink", rendered)
        self.assertIn("Topic title: National Cheddar Day", rendered)
        self.assertIn("USDA cheese data", rendered)
        self.assertIn("Wisconsin produces the most cheese.", rendered)
        self.assertIn("The first answer was ambiguous.", rendered)

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
            "source_urls": ["https://example.com/cheese-production"],
            "topic": "U.S. cheese production",
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

            search_results = (
                WebSearchResult(
                    title="Cheese data",
                    url="https://example.com/cheese-production",
                    snippet="Wisconsin produces the most cheese.",
                ),
            )
            candidate = generator(
                topic,
                "Food & Drink",
                date(2026, 7, 10),
                search_results,
                ("previous failure",),
            )

        self.assertEqual(candidate.question.prompt, "Which state produces the most cheese?")
        self.assertEqual(candidate.question.options["C"], "Wisconsin")
        self.assertEqual(candidate.question.correct_option, "C")
        self.assertEqual(candidate.topic_source, topic)
        self.assertEqual(candidate.category, "Food & Drink")
        self.assertEqual(candidate.source_urls, ("https://example.com/cheese-production",))
        self.assertEqual(candidate.source_evidence, ("Wisconsin produces the most cheese.",))

        call = client.calls[0]
        self.assertEqual(call["prompt_path"], prompt_path)
        self.assertEqual(call["schema_name"], "qotd_generated_question")
        request_payload = cast(dict[str, Any], call["payload"])
        self.assertEqual(
            set(request_payload),
            {"category", "topic", "evidence", "prior_rejection_reasons"},
        )
        self.assertEqual(request_payload["category"], "Food & Drink")
        self.assertEqual(
            request_payload["topic"],
            {"title": "National Cheddar Day", "summary": "A food holiday."},
        )
        self.assertEqual(request_payload["evidence"][0]["title"], "Cheese data")
        self.assertEqual(request_payload["prior_rejection_reasons"], ["previous failure"])


if __name__ == "__main__":
    unittest.main()
