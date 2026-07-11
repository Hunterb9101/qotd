"""Category balancing rules for QOTD question selection."""

from __future__ import annotations

import random
from collections import Counter
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any


QUESTION_CATEGORIES = (
    "Science & Nature",
    "Technology",
    "Sports",
    "Movies & TV",
    "Music",
    "Food & Drink",
    "History",
    "Geography",
    "Books & Arts",
    "Business & Brands",
    "Language",
    "Games & Leisure",
)


@dataclass(frozen=True)
class CategoryPolicy:
    """Rules for choosing underused broad trivia categories."""

    categories: tuple[str, ...] = QUESTION_CATEGORIES
    lookback_days: int = 30


def recent_category_counts(
    question_records: list[dict[str, Any]],
    *,
    game_date: date,
    policy: CategoryPolicy = CategoryPolicy(),
) -> dict[str, int]:
    """Count known category usage in the configured lookback window."""

    cutoff = game_date - timedelta(days=policy.lookback_days)
    counts: Counter[str] = Counter({category: 0 for category in policy.categories})
    allowed_categories = set(policy.categories)
    for record in question_records:
        category = str(record.get("category") or "").strip()
        if category not in allowed_categories:
            continue
        try:
            record_date = date.fromisoformat(str(record["game_date"]))
        except (KeyError, TypeError, ValueError):
            continue
        if cutoff <= record_date < game_date:
            counts[category] += 1
    return dict(counts)


def category_priority(
    question_records: list[dict[str, Any]],
    *,
    game_date: date,
    policy: CategoryPolicy = CategoryPolicy(),
) -> tuple[str, ...]:
    """Return categories ordered from most underused to most used.

    Ties are shuffled with a deterministic per-day seed so reruns are stable.
    """

    counts = recent_category_counts(question_records, game_date=game_date, policy=policy)
    grouped: dict[int, list[str]] = {}
    for category in policy.categories:
        grouped.setdefault(counts[category], []).append(category)

    rng = random.Random(game_date.isoformat())
    ordered: list[str] = []
    for count in sorted(grouped):
        tied_categories = grouped[count]
        rng.shuffle(tied_categories)
        ordered.extend(tied_categories)
    return tuple(ordered)
