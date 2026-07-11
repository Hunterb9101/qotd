"""Determine which trivia categories should be tried first."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from qotd.domain.categories import CategoryPolicy, category_priority
from qotd.external.storage.core import StorageClient


@dataclass(frozen=True)
class DetermineCategoryOrderConfig:
    """Configuration for category-order planning.

    This use case reads recent QOTD history and returns broad trivia categories
    from most underused to most used. It does not search for topics, call AI, or
    generate questions.
    """

    game_date: date
    state_store: StorageClient
    category_policy: CategoryPolicy = CategoryPolicy()


@dataclass(frozen=True)
class DetermineCategoryOrderResult:
    """Ordered category plan for a generation run."""

    categories: tuple[str, ...]


def determine_category_order(config: DetermineCategoryOrderConfig) -> DetermineCategoryOrderResult:
    """Return broad trivia categories ordered by recent underuse."""

    question_records = config.state_store.read_question_records()
    return DetermineCategoryOrderResult(
        categories=category_priority(
            question_records,
            game_date=config.game_date,
            policy=config.category_policy,
        )
    )
