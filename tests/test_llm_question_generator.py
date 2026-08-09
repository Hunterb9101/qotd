from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

from qotd.domain.categories import QUESTION_CATEGORIES
from qotd.domain.generator import shuffle_answer_options
from qotd.domain.models import GeneratedQuestionCandidate, Question, QuestionTopic
from qotd.external.llm.openai import render_prompt
from qotd.external.web_search.core import WebSearchResult
from qotd.usecases.discover_question_topic import (
    DEFAULT_TOPIC_DISCOVERY_PROMPT_PATH,
    LLMTopicDiscoverer,
)
from qotd.usecases.generate_question import (
    DEFAULT_EVALUATION_PROMPT_PATH,
    DEFAULT_PROMPT_PATH,
    GenerateQuestionSamplesConfig,
    LLMQuestionEvaluator,
    LLMQuestionGenerator,
    QUESTION_STORY_ANGLES,
    QUESTION_SUBJECT_LENSES,
    QuestionGenerator,
    choose_categories,
    choose_lens_pairs,
    generate_question_samples,
)
from qotd.usecases.repair_question import (
    DEFAULT_REPAIR_PROMPT_PATH,
    RepairGeneratedQuestion,
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
        tools: tuple[dict[str, Any], ...] = (),
    ) -> Any:
        self.calls.append(
            {
                "prompt_path": prompt_path,
                "payload": payload,
                "response_model": response_model,
                "schema_name": schema_name,
                "max_output_tokens": max_output_tokens,
                "tools": tools,
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
    def candidate(self, topic: QuestionTopic, category: str = "Food & Drink") -> GeneratedQuestionCandidate:
        return GeneratedQuestionCandidate(
            question=Question(
                game_date="2026-07-11",
                prompt="Which state produces the most cheese?",
                options={"A": "California", "B": "New York", "C": "Wisconsin", "D": "Texas"},
                correct_option="C",
                source_note="USDA cheese production data.",
                source_url="https://example.com/cheese-production",
            ),
            topic_source=topic,
            category=category,
            topic="U.S. cheese production",
            source_urls=("https://example.com/cheese-production",),
            source_evidence=("Wisconsin produces the most cheese.",),
        )

    def test_shuffle_answer_options_keeps_correct_answer_with_its_new_label(self) -> None:
        options = {"A": "California", "B": "New York", "C": "Wisconsin", "D": "Texas"}
        with patch("qotd.domain.generator.random.shuffle", side_effect=lambda answers: answers.reverse()):
            shuffled_options, correct_option = shuffle_answer_options(options, "C")

        self.assertEqual(
            shuffled_options,
            {"A": "Texas", "B": "Wisconsin", "C": "New York", "D": "California"},
        )
        self.assertEqual(correct_option, "B")

    def test_generate_samples_uses_supplied_topic_and_requested_count(self) -> None:
        calls: list[tuple[QuestionTopic, str]] = []

        def generate(topic, category, game_date, evidence, rejection_reasons):
            calls.append((topic, category))
            return LLMQuestionGenerator(FakeLLMClient({
                "prompt": "Which state produces the most cheese?",
                "options": {"A": "California", "B": "New York", "C": "Wisconsin", "D": "Texas"},
                "correct_option": "C",
                "source_note": "USDA cheese production data.",
                "sources": [
                    {
                        "url": "https://example.com/cheese-production",
                        "evidence": "Wisconsin produces the most cheese.",
                    }
                ],
                "topic": "U.S. cheese production",
            }))(topic, category, game_date, evidence, rejection_reasons)

        candidates = generate_question_samples(
            GenerateQuestionSamplesConfig(
                topic="Cheese history",
                sample_count=3,
                game_date=date(2026, 7, 11),
                seed="test-seed",
            ),
            generate_question=generate,
        )

        self.assertEqual(len(candidates), 3)
        self.assertEqual(len(calls), 3)
        self.assertEqual(calls[0][0].title, "Cheese history")
        self.assertEqual(calls[0][0].summary, "Research this topic with web search before writing the question.")
        self.assertEqual(len({call[0].lenses for call in calls}), 3)
        self.assertTrue(all(len(call[0].lenses) == 2 for call in calls))
        self.assertEqual(len({category for _, category in calls}), 3)
        self.assertTrue(all(category in QUESTION_CATEGORIES for _, category in calls))

    def test_choose_lens_pairs_is_reproducible_and_unique_within_a_batch(self) -> None:
        first = choose_lens_pairs(4, seed="same-seed")
        second = choose_lens_pairs(4, seed="same-seed")

        self.assertEqual(first, second)
        self.assertEqual(len(set(first)), 4)
        self.assertTrue(all(subject in QUESTION_SUBJECT_LENSES for subject, _ in first))
        self.assertTrue(all(angle in QUESTION_STORY_ANGLES for _, angle in first))

    def test_choose_categories_is_reproducible_and_avoids_early_repeats(self) -> None:
        first = choose_categories(4, seed="same-seed")
        second = choose_categories(4, seed="same-seed")

        self.assertEqual(first, second)
        self.assertEqual(len(set(first)), 4)
        self.assertTrue(all(category in QUESTION_CATEGORIES for category in first))

    def test_generate_samples_validates_topic_and_count(self) -> None:
        with self.assertRaisesRegex(ValueError, "topic cannot be blank"):
            generate_question_samples(
                GenerateQuestionSamplesConfig("  ", 1, date(2026, 7, 11)),
            generate_question=cast(QuestionGenerator, lambda *args: None),
        )
        with self.assertRaisesRegex(ValueError, "sample count must be at least 1"):
            generate_question_samples(
                GenerateQuestionSamplesConfig("cheese", 0, date(2026, 7, 11)),
                generate_question=cast(QuestionGenerator, lambda *args: None),
            )

    def test_generate_samples_retries_after_llm_quality_rejection(self) -> None:
        topic_seen: list[tuple[str, ...]] = []
        repair_issues: list[tuple[str, ...]] = []
        evaluations = iter((("The prompt gives away the answer.",), ()))

        def generate(topic, category, game_date, evidence, rejection_reasons):
            topic_seen.append(topic.lenses)
            return self.candidate(topic, category)

        def repair(candidate, issues):
            repair_issues.append(issues)
            return candidate

        candidates = generate_question_samples(
            GenerateQuestionSamplesConfig(
                "cheese",
                1,
                date(2026, 7, 11),
                category="Food & Drink",
                attempts=2,
            ),
            generate_question=generate,
            repair_question=repair,
            evaluate_question=lambda candidate: next(evaluations),
        )

        self.assertEqual(len(candidates), 1)
        self.assertEqual(len(topic_seen), 1)
        self.assertEqual(repair_issues, [("The prompt gives away the answer.",)])

    def test_repair_usecase_uses_focused_prompt_and_preserves_candidate_context(self) -> None:
        client = FakeLLMClient(
            {
                "prompt": "Which U.S. state produces the most cheese?",
                "options": {"A": "California", "B": "New York", "C": "Wisconsin", "D": "Texas"},
                "correct_option": "C",
                "source_note": "USDA cheese production data.",
            }
        )
        topic = QuestionTopic("Cheese", "A food topic.", "")
        candidate = self.candidate(topic)

        repaired = RepairGeneratedQuestion(llm_client=client)(
            candidate,
            ("The original wording was ambiguous.",),
        )

        self.assertEqual(repaired.question.prompt, "Which U.S. state produces the most cheese?")
        self.assertEqual(repaired.question.options[repaired.question.correct_option], "Wisconsin")
        self.assertEqual(repaired.topic_source, candidate.topic_source)
        self.assertEqual(repaired.category, candidate.category)
        self.assertEqual(repaired.topic, candidate.topic)
        self.assertEqual(repaired.source_urls, candidate.source_urls)
        self.assertEqual(repaired.source_evidence, candidate.source_evidence)
        call = client.calls[0]
        self.assertEqual(call["prompt_path"], DEFAULT_REPAIR_PROMPT_PATH)
        self.assertEqual(call["schema_name"], "qotd_repaired_question")
        self.assertEqual(call["payload"]["issues"], ["The original wording was ambiguous."])
        self.assertEqual(call["payload"]["question"]["correct_answer"], "Wisconsin")
        self.assertEqual(call["tools"], ())

    def test_llm_evaluator_returns_actionable_rejection_reasons(self) -> None:
        client = FakeLLMClient(
            {
                "approved": False,
                "rejection_reasons": ["The prompt paraphrases the correct answer."],
            }
        )
        topic = QuestionTopic("Cheese", "A food topic.", "")
        evaluator = LLMQuestionEvaluator(llm_client=client)

        reasons = evaluator(self.candidate(topic))

        self.assertEqual(reasons, ("The prompt paraphrases the correct answer.",))
        call = client.calls[0]
        self.assertEqual(call["prompt_path"], DEFAULT_EVALUATION_PROMPT_PATH)
        self.assertEqual(call["schema_name"], "qotd_question_quality_review")
        self.assertEqual(call["payload"]["question"]["correct_answer"], "Wisconsin")
        self.assertEqual(call["tools"], ())

    def test_evaluation_prompt_checks_answer_leakage_and_unfair_options(self) -> None:
        prompt = DEFAULT_EVALUATION_PROMPT_PATH.read_text(encoding="utf-8")

        self.assertIn("close paraphrase", prompt)
        self.assertIn("points conspicuously to the correct choice", prompt)
        self.assertIn("More than one option reasonably answers", prompt)

    def test_topic_discoverer_uses_web_search_and_maps_entity_topics(self) -> None:
        client = FakeLLMClient(
            {
                "topics": [
                    {
                        "title": "Super Mario",
                        "summary": "A new Mario release can lead into the character's history.",
                    },
                    {
                        "title": "The Legend of Zelda",
                        "summary": "A new Zelda release can lead into the series' influences.",
                    },
                ]
            }
        )
        discoverer = LLMTopicDiscoverer(llm_client=client)

        topics = discoverer.search("Games & Leisure; as of date: 2026-07-11", limit=1)

        self.assertEqual(len(topics), 1)
        self.assertEqual(topics[0].title, "Super Mario")
        self.assertEqual(topics[0].snippet, "A new Mario release can lead into the character's history.")
        self.assertEqual(topics[0].url, "")
        call = client.calls[0]
        self.assertEqual(call["prompt_path"], DEFAULT_TOPIC_DISCOVERY_PROMPT_PATH)
        self.assertEqual(call["payload"]["limit"], 1)
        self.assertEqual(call["tools"], ({"type": "web_search"},))

    def test_topic_discovery_prompt_defines_timely_entity_lanes(self) -> None:
        prompt = DEFAULT_TOPIC_DISCOVERY_PROMPT_PATH.read_text(encoding="utf-8")

        self.assertIn("Approachable current events", prompt)
        self.assertIn("self-proclaimed food days", prompt)
        self.assertIn("New entertainment releases", prompt)
        self.assertIn("do not use an article headline", prompt)
        self.assertIn("brainstorming, not question research", prompt)

    def test_default_prompt_is_packaged_and_contains_generation_guidance(self) -> None:
        prompt = DEFAULT_PROMPT_PATH.read_text(encoding="utf-8")

        self.assertIn("exactly four distinct options labeled A, B, C, and D", prompt)
        self.assertIn("exactly one option is correct", prompt)
        self.assertIn("retrieved source evidence must support only that correct answer", prompt)
        self.assertIn("informal, conversational, and human", prompt)
        self.assertIn("accessible-to-moderate difficulty", prompt)
        self.assertIn("what is surprising, strange, or amusing", prompt)
        self.assertIn("Use the subject lens to choose the human, cultural, or practical part", prompt)
        self.assertIn("Use the story angle to choose what makes the fact memorable", prompt)
        self.assertIn("It may itself be the correct answer", prompt)
        self.assertIn("do not name the topic in the question", prompt)
        self.assertIn("Do not default to first, earliest, oldest", prompt)
        self.assertIn("Do not treat other names, examples, foods, places, dates, or facts", prompt)
        self.assertIn("Invent three plausible but incorrect distractors", prompt)
        self.assertIn("same semantic type", prompt)
        self.assertIn("must support only that correct answer among the four options", prompt)
        self.assertIn("academic, institutional, encyclopedic, or promotional", prompt)
        self.assertIn("avoid legalese, bureaucratic phrasing", prompt)
        self.assertIn("describe its practical effect in plain language", prompt)
        self.assertIn("Do not mention statute numbers, code sections", prompt)
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
                "lenses": [
                    "language, slang, nicknames, and catchphrases",
                    "a crossover between different cultures or fields",
                ],
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
        self.assertIn("Subject lens: language, slang, nicknames, and catchphrases", rendered)
        self.assertIn("Story angle: a crossover between different cultures or fields", rendered)

    def test_default_prompt_requires_web_research_without_supplied_evidence(self) -> None:
        rendered = render_prompt(
            DEFAULT_PROMPT_PATH,
            {
                "category": "Food & Drink",
                "topic": {"title": "Cheese history", "summary": "Research the topic."},
                "lenses": [
                    "traditions, celebrations, and rituals",
                    "an unusual exception or quirky rule",
                ],
                "evidence": [],
                "prior_rejection_reasons": [],
            },
        )

        self.assertIn("Use web search to research the topic", rendered)

    def test_repair_prompt_requires_small_evidence_preserving_changes(self) -> None:
        prompt = DEFAULT_REPAIR_PROMPT_PATH.read_text(encoding="utf-8")

        self.assertIn("Revise the candidate only enough", prompt)
        self.assertIn("preserve its category, topic, underlying fact, source evidence", prompt)
        self.assertIn("Prefer a small editorial correction over a rewrite", prompt)
        self.assertIn("Do not add, replace, or invent sources", prompt)

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
            "sources": [
                {
                    "url": "https://example.com/cheese-production",
                    "evidence": "Wisconsin produces the most cheese.",
                }
            ],
            "topic": "U.S. cheese production",
        }
        client = FakeLLMClient(output)
        with tempfile.TemporaryDirectory() as temp_dir:
            prompt_path = Path(temp_dir) / "prompt.md"
            prompt_path.write_text("Generate a question.", encoding="utf-8")

            generator = LLMQuestionGenerator(
                llm_client=client,
                prompt_path=prompt_path,
                use_web_search=True,
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
            with patch(
                "qotd.domain.generator.random.shuffle", side_effect=lambda answers: answers.reverse()
            ):
                candidate = generator(
                    topic,
                    "Food & Drink",
                    date(2026, 7, 10),
                    search_results,
                    ("previous failure",),
                )

        self.assertEqual(candidate.question.prompt, "Which state produces the most cheese?")
        self.assertEqual(candidate.question.options["B"], "Wisconsin")
        self.assertEqual(candidate.question.correct_option, "B")
        self.assertEqual(candidate.topic_source, topic)
        self.assertEqual(candidate.category, "Food & Drink")
        self.assertEqual(candidate.source_urls, ("https://example.com/cheese-production",))
        self.assertEqual(candidate.source_evidence, ("Wisconsin produces the most cheese.",))

        call = client.calls[0]
        self.assertEqual(call["prompt_path"], prompt_path)
        self.assertEqual(call["schema_name"], "qotd_generated_question")
        self.assertEqual(call["tools"], ({"type": "web_search"},))
        request_payload = cast(dict[str, Any], call["payload"])
        self.assertEqual(
            set(request_payload),
            {"category", "topic", "lenses", "evidence", "prior_rejection_reasons"},
        )
        self.assertEqual(request_payload["category"], "Food & Drink")
        self.assertEqual(
            request_payload["topic"],
            {"title": "National Cheddar Day", "summary": "A food holiday."},
        )
        self.assertEqual(request_payload["lenses"], [])
        self.assertEqual(request_payload["evidence"][0]["title"], "Cheese data")
        self.assertEqual(request_payload["prior_rejection_reasons"], ["previous failure"])


if __name__ == "__main__":
    unittest.main()
