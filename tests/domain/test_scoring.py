from __future__ import annotations

from datetime import datetime

from qotd.domain.models import ReplyCandidate, StoredQuestion
from qotd.domain.scoring import score_replies


def _question() -> StoredQuestion:
    return StoredQuestion(
        game_date="2026-07-09",
        prompt="Which planet has the Great Red Spot?",
        options={"A": "Mars", "B": "Jupiter", "C": "Saturn", "D": "Neptune"},
        correct_option="B",
        source_note="Jupiter has the Great Red Spot.",
        source_url="https://example.com/jupiter",
        source="generated",
        gmail_message_id="question-1",
        created_at="2026-07-09T18:00:00+00:00",
    )


def _reply(email: str, answer: str) -> ReplyCandidate:
    return ReplyCandidate(
        game_date="2026-07-09",
        sender_email=email,
        gmail_message_id=f"reply:{email}",
        received_at="2026-07-10T06:30:00-06:00",
        body_text=answer,
    )


def test_monthly_roster_contains_only_current_positive_scorers() -> None:
    result = score_replies(
        question=_question(),
        replies=[_reply("new-player@example.com", "A")],
        cutoff_at=datetime.fromisoformat("2026-07-10T07:00:00-06:00"),
        processed_at=datetime.fromisoformat("2026-07-10T14:00:00+00:00"),
        existing_monthly_score_records=[
            {"series": "0726", "email": "active@example.com", "points": 2},
            {"series": "0726", "email": "zero@example.com", "points": 0},
            {"series": "0626", "email": "past@example.com", "points": 5},
        ],
    )

    assert [(score.email, score.points) for score in result.standings] == [
        ("active@example.com", 2)
    ]
    assert result.no_response == ("active@example.com",)
    assert result.monthly_score_updates == ()


def test_correct_reply_enrolls_participant_in_current_month_standings() -> None:
    result = score_replies(
        question=_question(),
        replies=[_reply("returning@example.com", "B")],
        cutoff_at=datetime.fromisoformat("2026-07-10T07:00:00-06:00"),
        processed_at=datetime.fromisoformat("2026-07-10T14:00:00+00:00"),
    )

    assert [(score.email, score.points) for score in result.standings] == [
        ("returning@example.com", 1)
    ]
    assert [(score.email, score.points) for score in result.monthly_score_updates] == [
        ("returning@example.com", 1)
    ]
