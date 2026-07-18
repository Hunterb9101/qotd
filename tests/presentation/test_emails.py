from __future__ import annotations

from qotd.domain.generator import generate_placeholder_question
from qotd.presentation.emails import build_participant_email


def test_group_delivery_routes_replies_to_sender_without_participant_headers() -> None:
    """Address a private Group without exposing individual participant addresses."""

    message = build_participant_email(
        generate_placeholder_question("2026-07-09"),
        "sender@example.com",
        delivery_address="qotd-group@googlegroups.com",
    )

    assert message["To"] == "qotd-group@googlegroups.com"
    assert message["Reply-To"] == "sender@example.com"
    assert message["Cc"] is None
    assert message["Bcc"] is None
