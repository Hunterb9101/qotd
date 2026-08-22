from __future__ import annotations

import unittest
from datetime import date

from qotd.domain.models import GeneratedQuestionCandidate, Question, QuestionTopic
from qotd.external.web_search.core import WebSearchResult
from qotd.usecases.generate_question import (
    GenerateResearchedQuestionConfig,
    LLMQuestionEvaluator,
    LLMQuestionGenerator,
    choose_category,
    choose_lens_pairs,
    generate_researched_question,
    validate_researched_candidate,
)
from qotd.usecases.discover_question_topic import LLMTopicDiscoverer
from qotd.usecases.repair_question import RepairGeneratedQuestion


class FakeWebSearchClient:
    def __init__(self, responses: list[tuple[WebSearchResult, ...]]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, int]] = []

    def search(self, query: str, *, limit: int = 5) -> tuple[WebSearchResult, ...]:
        self.calls.append((query, limit))
        index = min(len(self.calls) - 1, len(self.responses) - 1)
        return self.responses[index]


class RecordingLLM:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.evaluation_count = 0

    def create_structured_response(self, **kwargs: object):
        self.calls.append(kwargs)
        model = kwargs["response_model"]
        schema_name = kwargs["schema_name"]
        if schema_name == "qotd_topic_discovery":
            return model.model_validate({"topics": [{"title": "Space", "summary": "Planet facts"}]})
        if schema_name == "qotd_generated_question":
            return model.model_validate(_generated_question_payload())
        if schema_name == "qotd_question_quality_review":
            self.evaluation_count += 1
            return model.model_validate({
                "approved": self.evaluation_count > 1,
                "rejection_reasons": [] if self.evaluation_count > 1 else ["Make the wording clearer"],
            })
        if schema_name == "qotd_repaired_question":
            return model.model_validate(_repaired_question_payload())
        raise AssertionError(f"Unexpected schema: {schema_name}")


def _generated_question_payload() -> dict[str, object]:
    return {
        "topic": "Mars",
        "prompt": "Which planet is known as the Red Planet?",
        "options": {"A": "Venus", "B": "Jupiter", "C": "Mars", "D": "Mercury"},
        "correct_option": "C",
        "source_note": "NASA facts",
        "sources": [{"url": "https://example.com/mars", "evidence": "Mars is the Red Planet."}],
    }


def _repaired_question_payload() -> dict[str, object]:
    return {
        "prompt": "Which planet is called the Red Planet?",
        "options": {"A": "Venus", "B": "Jupiter", "C": "Mars", "D": "Mercury"},
        "correct_option": "C",
        "source_note": "NASA facts",
    }


def evidence(*, snippet: str = "USDA reports Wisconsin produced the most cheese in the United States.") -> WebSearchResult:
    return WebSearchResult(
        title="Cheese production facts",
        url="https://www.usda.gov/cheese-production",
        snippet=snippet,
    )


def candidate_for(topic: QuestionTopic, category: str, game_date: date) -> GeneratedQuestionCandidate:
    result = evidence()
    return GeneratedQuestionCandidate(
        question=Question(
            game_date=game_date.isoformat(),
            prompt="Which state produces the most cheese in the United States?",
            options={"A": "California", "B": "New York", "C": "Wisconsin", "D": "Texas"},
            correct_option="C",
            source_note="USDA production data supports the answer.",
            source_url=result.url,
        ),
        topic_source=topic,
        category=category,
        topic="U.S. cheese production",
        source_urls=(result.url,),
        source_evidence=(result.snippet,),
    )


class ResearchedQuestionGenerationTests(unittest.TestCase):
    def test_llm_calls_share_the_publish_question_usecase_run_id(self) -> None:
        llm = RecordingLLM()

        generate_researched_question(
            GenerateResearchedQuestionConfig(
                game_date=date(2026, 7, 10), categories=("Science",), usecase_run_id="publish-run"
            ),
            search_client=LLMTopicDiscoverer(llm_client=llm),
            generate_question=LLMQuestionGenerator(llm_client=llm),
            repair_question=RepairGeneratedQuestion(llm_client=llm),
            evaluate_question=LLMQuestionEvaluator(llm_client=llm),
        )

        self.assertEqual(
            [call["prompt_path"].stem for call in llm.calls],
            [
                "discover_question_topics",
                "generate_question_for_topic",
                "evaluate_generated_question",
                "repair_generated_question",
                "evaluate_generated_question",
            ],
        )
        self.assertEqual({call["use_case"] for call in llm.calls}, {"publish_question"})
        self.assertEqual({call["usecase_run_id"] for call in llm.calls}, {"publish-run"})

    def test_category_selection_is_reproducible_with_game_date_seed(self) -> None:
        categories = ("Science", "History", "Food")

        first = choose_category(categories, seed=date(2026, 7, 10).isoformat())
        second = choose_category(categories, seed=date(2026, 7, 10).isoformat())

        self.assertEqual(first, second)
        self.assertIn(first, categories)

    def test_flow_searches_category_and_returns_source_backed_contract(self) -> None:
        search = FakeWebSearchClient([(evidence(),)])

        result = generate_researched_question(
            GenerateResearchedQuestionConfig(
                game_date=date(2026, 7, 10),
                categories=("Food & Drink",),
                seed="stable",
            ),
            search_client=search,
            generate_question=lambda topic, category, game_date, results, reasons: candidate_for(
                topic, category, game_date
            ),
        )

        self.assertEqual(result.candidate.category, "Food & Drink")
        self.assertEqual(result.candidate.topic, "U.S. cheese production")
        self.assertEqual(result.candidate.source_urls, (evidence().url,))
        self.assertIn("timely creative directions", search.calls[0][0])
        expected_lenses = choose_lens_pairs(1, seed="stable")[0]
        self.assertEqual(result.candidate.topic_source.lenses, expected_lenses)
        self.assertIn(f"subject lens: {expected_lenses[0]}", search.calls[0][0])
        self.assertIn(f"story angle: {expected_lenses[1]}", search.calls[0][0])

    def test_flow_uses_direction_only_topic_then_accepts_generator_research(self) -> None:
        direction = WebSearchResult(
            title="Super Mario",
            url="",
            snippet="A new release is a timely hook into the character's history.",
        )
        search = FakeWebSearchClient([(direction,)])
        generation_evidence: list[tuple[WebSearchResult, ...]] = []

        def generate(topic, category, game_date, results, reasons):
            generation_evidence.append(results)
            return candidate_for(topic, category, game_date)

        result = generate_researched_question(
            GenerateResearchedQuestionConfig(
                game_date=date(2026, 7, 10),
                categories=("Games & Leisure",),
                seed="stable",
            ),
            search_client=search,
            generate_question=generate,
        )

        self.assertEqual(result.candidate.topic_source.title, "Super Mario")
        self.assertEqual(result.candidate.topic_source.source_url, "")
        self.assertEqual(generation_evidence, [()])

    def test_whole_flow_retries_after_unsupported_answer(self) -> None:
        unsupported = evidence(snippet="USDA publishes annual dairy statistics.")
        search = FakeWebSearchClient([(unsupported,), (evidence(),)])
        generated_reasons: list[tuple[str, ...]] = []

        def generate(
            topic: QuestionTopic,
            category: str,
            game_date: date,
            results: tuple[WebSearchResult, ...],
            reasons: tuple[str, ...],
        ) -> GeneratedQuestionCandidate:
            generated_reasons.append(reasons)
            candidate = candidate_for(topic, category, game_date)
            selected = results[0]
            return GeneratedQuestionCandidate(
                question=Question(
                    game_date=candidate.question.game_date,
                    prompt=candidate.question.prompt,
                    options=candidate.question.options,
                    correct_option=candidate.question.correct_option,
                    source_note=candidate.question.source_note,
                    source_url=selected.url,
                ),
                topic_source=topic,
                category=category,
                topic=candidate.topic,
                source_urls=(selected.url,),
                source_evidence=(selected.snippet,),
            )

        result = generate_researched_question(
            GenerateResearchedQuestionConfig(date(2026, 7, 10), categories=("Food",), attempts=2),
            search_client=search,
            generate_question=generate,
        )

        self.assertEqual(result.attempts_used, 2)
        self.assertIn("does not support", result.rejection_reasons[0])
        self.assertEqual(len(generated_reasons), 2)
        self.assertTrue(generated_reasons[1])

    def test_whole_flow_retries_after_llm_quality_rejection(self) -> None:
        search = FakeWebSearchClient([(evidence(),), (evidence(),)])
        evaluations = iter((("The wording gives away Wisconsin.",), ()))
        generated_candidates: list[GeneratedQuestionCandidate] = []
        repair_calls: list[tuple[GeneratedQuestionCandidate, tuple[str, ...]]] = []

        def generate(topic, category, game_date, results, reasons):
            candidate = candidate_for(topic, category, game_date)
            generated_candidates.append(candidate)
            return candidate

        def repair(candidate, issues):
            repair_calls.append((candidate, issues))
            return candidate

        result = generate_researched_question(
            GenerateResearchedQuestionConfig(
                date(2026, 7, 10),
                categories=("Food",),
                attempts=2,
            ),
            search_client=search,
            generate_question=generate,
            repair_question=repair,
            evaluate_question=lambda candidate: next(evaluations),
        )

        self.assertEqual(result.attempts_used, 2)
        self.assertIn("gives away", result.rejection_reasons[0])
        self.assertEqual(len(search.calls), 1)
        self.assertEqual(len(generated_candidates), 1)
        self.assertEqual(repair_calls[0][0], generated_candidates[0])
        self.assertEqual(repair_calls[0][1], ("The wording gives away Wisconsin.",))

    def test_whole_flow_regenerates_when_repair_leaves_answer_leakage_unchanged(self) -> None:
        search = FakeWebSearchClient([(evidence(),), (evidence(),)])
        generated_candidates: list[GeneratedQuestionCandidate] = []
        repair_calls: list[tuple[GeneratedQuestionCandidate, tuple[str, ...]]] = []

        def generate(topic, category, game_date, results, reasons):
            candidate = candidate_for(topic, category, game_date)
            if not generated_candidates:
                candidate = GeneratedQuestionCandidate(
                    question=Question(
                        game_date=candidate.question.game_date,
                        prompt="Why is Wisconsin the biggest cheese producer?",
                        options=candidate.question.options,
                        correct_option=candidate.question.correct_option,
                        source_note=candidate.question.source_note,
                        source_url=candidate.question.source_url,
                    ),
                    topic_source=candidate.topic_source,
                    category=candidate.category,
                    topic=candidate.topic,
                    source_urls=candidate.source_urls,
                    source_evidence=candidate.source_evidence,
                )
            generated_candidates.append(candidate)
            return candidate

        def repair(candidate, issues):
            repair_calls.append((candidate, issues))
            return candidate

        result = generate_researched_question(
            GenerateResearchedQuestionConfig(date(2026, 7, 10), categories=("Food",), attempts=3),
            search_client=search,
            generate_question=generate,
            repair_question=repair,
        )

        self.assertEqual(result.attempts_used, 3)
        self.assertEqual(len(generated_candidates), 2)
        self.assertEqual(len(repair_calls), 1)
        self.assertEqual(repair_calls[0][1], ("question prompt leaks the correct answer",))
        self.assertIn("repair returned a candidate with unchanged issues", result.rejection_reasons[1])

    def test_exhaustion_alerts_and_fails_closed(self) -> None:
        search = FakeWebSearchClient([()])
        alerts: list[str] = []

        with self.assertRaisesRegex(RuntimeError, "no viable evidence"):
            generate_researched_question(
                GenerateResearchedQuestionConfig(date(2026, 7, 10), categories=("History",), attempts=2),
                search_client=search,
                generate_question=lambda *args: candidate_for(args[0], args[1], args[2]),
                alert_organizer=alerts.append,
            )

        self.assertEqual(len(alerts), 1)
        self.assertEqual(len(search.calls), 2)

    def test_validation_rejects_unretrieved_url_and_multiple_plausible_answers(self) -> None:
        topic = QuestionTopic(evidence().title, evidence().snippet, evidence().url)
        candidate = candidate_for(topic, "Food", date(2026, 7, 10))

        with self.assertRaisesRegex(ValueError, "come from retrieved evidence"):
            validate_researched_candidate(candidate, ())

        ambiguous = evidence(snippet="Wisconsin and California both produce the most cheese.")
        with self.assertRaisesRegex(ValueError, "multiple plausible"):
            validate_researched_candidate(candidate, (ambiguous,))

    def test_validation_rejects_answer_leakage_and_volatile_claims(self) -> None:
        topic = QuestionTopic(evidence().title, evidence().snippet, evidence().url)
        base = candidate_for(topic, "Food", date(2026, 7, 10))

        leaked = GeneratedQuestionCandidate(
            question=Question(
                game_date=base.question.game_date,
                prompt="Why is Wisconsin the biggest cheese producer?",
                options=base.question.options,
                correct_option="C",
                source_note=base.question.source_note,
                source_url=base.question.source_url,
            ),
            topic_source=topic,
            category="Food",
            topic=base.topic,
            source_urls=base.source_urls,
            source_evidence=base.source_evidence,
        )
        with self.assertRaisesRegex(ValueError, "leaks"):
            validate_researched_candidate(leaked, (evidence(),))

        volatile = GeneratedQuestionCandidate(
            question=Question(
                game_date=base.question.game_date,
                prompt="Which state currently produces the most cheese?",
                options=base.question.options,
                correct_option="C",
                source_note=base.question.source_note,
                source_url=base.question.source_url,
            ),
            topic_source=topic,
            category="Food",
            topic=base.topic,
            source_urls=base.source_urls,
            source_evidence=base.source_evidence,
        )
        with self.assertRaisesRegex(ValueError, "volatile"):
            validate_researched_candidate(volatile, (evidence(),))


if __name__ == "__main__":
    unittest.main()
