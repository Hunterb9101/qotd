from __future__ import annotations

import unittest
from datetime import date
from typing import Any

from qotd.domain.categories import CategoryPolicy, category_priority, recent_category_counts
from qotd.domain.models import Question
from qotd.usecases.determine_category_order import DetermineCategoryOrderConfig, determine_category_order
from qotd.usecases.generate_question_for_topic import (
    GeneratedQuestionCandidate,
    GenerateQuestionForTopicConfig,
    QuestionTopic,
    VerificationResult,
    check_question_novelty,
    generate_question_for_topic,
)
from qotd.usecases.send_question import SendQuestionConfig, send_question
from tests.support import InMemoryStateStore


def question_for(game_date: date, *, prompt: str = "Which state produces the most cheese?") -> Question:
    return Question(
        game_date=game_date.isoformat(),
        prompt=prompt,
        options={
            "A": "California",
            "B": "New York",
            "C": "Wisconsin",
            "D": "Texas",
        },
        correct_option="C",
        source_note="USDA data identifies Wisconsin as the top cheese-producing state.",
        source_url="https://example.com/cheese-production",
    )


def candidate_for(
    game_date: date,
    *,
    category: str,
    topic_source: QuestionTopic | None = None,
    topic: str = "U.S. cheese production",
    entities: tuple[str, ...] = ("Wisconsin",),
) -> GeneratedQuestionCandidate:
    return GeneratedQuestionCandidate(
        question=question_for(game_date),
        topic_source=topic_source
        or QuestionTopic("National Cheddar Day", "A food holiday.", "https://example.com/cheddar-day"),
        category=category,
        subcategory="Cheese",
        topic=topic,
        entities=entities,
    )


class Phase5QuestionSelectionTests(unittest.TestCase):
    def test_recent_category_counts_include_underused_zero_categories(self) -> None:
        records: list[dict[str, Any]] = [
            {"game_date": "2026-07-08", "category": "Food & Drink"},
            {"game_date": "2026-06-01", "category": "History"},
            {"game_date": "2026-07-07", "category": ""},
        ]
        policy = CategoryPolicy(categories=("Food & Drink", "History"), lookback_days=30)

        counts = recent_category_counts(records, game_date=date(2026, 7, 10), policy=policy)

        self.assertEqual(counts, {"Food & Drink": 1, "History": 0})

    def test_category_priority_is_deterministic_for_ties(self) -> None:
        policy = CategoryPolicy(categories=("Science", "History", "Food"), lookback_days=30)

        first = category_priority([], game_date=date(2026, 7, 10), policy=policy)
        second = category_priority([], game_date=date(2026, 7, 10), policy=policy)

        self.assertEqual(first, second)
        self.assertEqual(set(first), {"Science", "History", "Food"})

    def test_determine_category_order_reads_state_store(self) -> None:
        store = InMemoryStateStore()
        store.question_records.append({"game_date": "2026-07-09", "category": "Food & Drink"})

        result = determine_category_order(
            DetermineCategoryOrderConfig(
                game_date=date(2026, 7, 10),
                state_store=store,
                category_policy=CategoryPolicy(categories=("History", "Food & Drink"), lookback_days=30),
            )
        )

        self.assertEqual(result.categories, ("History", "Food & Drink"))

    def test_generate_question_for_topic_retries_after_failed_verification(self) -> None:
        store = InMemoryStateStore()
        topic_source = QuestionTopic("National Cheddar Day", "A food holiday.", "https://example.com/cheddar-day")
        generated_attempts: list[int] = []

        def generate_question(
            topic: QuestionTopic,
            category: str,
            game_date: date,
            rejection_reasons: tuple[str, ...],
        ) -> GeneratedQuestionCandidate:
            generated_attempts.append(len(rejection_reasons))
            return candidate_for(game_date, category=category, topic_source=topic)

        def verify_question(candidate: GeneratedQuestionCandidate) -> VerificationResult:
            if len(generated_attempts) == 1:
                return VerificationResult(passed=False, reason="source does not support the answer")
            return VerificationResult(passed=True, source_urls=(candidate.question.source_url,), confidence="high")

        result = generate_question_for_topic(
            GenerateQuestionForTopicConfig(
                game_date=date(2026, 7, 10),
                category="Food & Drink",
                topic=topic_source,
                state_store=store,
                attempts=2,
            ),
            generate_question=generate_question,
            verify_question=verify_question,
        )

        self.assertEqual(generated_attempts, [0, 1])
        self.assertEqual(result.candidate.topic_source.title, "National Cheddar Day")
        self.assertIn("verification failed", result.rejection_reasons[0])

    def test_novelty_rejects_recent_entity_repeat(self) -> None:
        records = [{"game_date": "2026-07-01", "entities": ["Wisconsin"], "topic": "Dairy brands"}]

        reason = check_question_novelty(
            candidate_for(date(2026, 7, 10), category="Food & Drink", topic="Cheese production"),
            records,
            game_date=date(2026, 7, 10),
            topic_days=30,
            entity_days=14,
        )

        self.assertEqual(reason, "entity repeated within 14 days: wisconsin")

    def test_send_question_can_use_injected_generator(self) -> None:
        store = InMemoryStateStore()

        result = send_question(
            SendQuestionConfig(
                game_date=date(2026, 7, 10),
                sender="***SECRET***",
                contact_group_name="QOTD Participants",
                state_store=store,
                gmail_user="***SECRET***",
                oauth_client_id="",
                oauth_client_secret="",
                oauth_refresh_token="",
                participant_emails=("player@example.com",),
                question_generator=lambda game_date, state_store: question_for(game_date, prompt="Injected question?"),
                dry_run=True,
            )
        )

        self.assertEqual(result.record.prompt, "Injected question?")
        self.assertIn("Injected question?", result.email_body)


if __name__ == "__main__":
    unittest.main()
