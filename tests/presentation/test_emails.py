from __future__ import annotations

from datetime import UTC, datetime

from qotd.domain.generator import generate_placeholder_question
from qotd.domain.models import ScoreboardLine, StoredQuestion
from qotd.presentation.emails import build_player_email


def test_group_delivery_routes_player_replies_to_sender_without_player_headers() -> None:
    """Address a private Group without exposing individual Player addresses."""

    message = build_player_email(
        generate_placeholder_question("2026-07-09"),
        "sender@example.com",
        delivery_address="qotd-group@googlegroups.com",
    )

    assert message["To"] == "qotd-group@googlegroups.com"
    assert message["Reply-To"] == "sender@example.com"
    assert message["Cc"] is None
    assert message["Bcc"] is None


def test_player_recap_uses_nicknames_and_falls_back_to_email() -> None:
    message = build_player_email(
        generate_placeholder_question("2026-09-01"),
        "sender@example.com",
        delivery_address="qotd-group@googlegroups.com",
        previous_question=StoredQuestion(
            game_date="2026-08-31", prompt="Previous?", options={"A": "One", "B": "Two", "C": "Three", "D": "Four"},
            correct_option="A", source_note="", source_url="", source="manual", gmail_message_id="previous",
            created_at=datetime(2026, 8, 31, tzinfo=UTC).isoformat(),
        ),
        point_earners=("Ada",),
        standings=(
            ScoreboardLine(series="0826", email="ada@example.com", points=3, nickname="Ada"),
            ScoreboardLine(series="0826", email="ben@example.com", points=1),
        ),
    )

    body = message.get_content()
    assert "Points earned:\n- Ada" in body
    assert "1. Ada — 3" in body
    assert "2. ben@example.com — 1" in body
    assert "- Ada with 3 points" in body
