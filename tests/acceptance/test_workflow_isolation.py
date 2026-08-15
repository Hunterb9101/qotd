"""Behavioral acceptance coverage for email workflow isolation."""

from datetime import UTC, date, datetime

import pytest

from qotd.domain.canonical import gmail_message_key
from qotd.domain.models import Question
from qotd.external.email.core import ParsedEmailMessage
from qotd.external.storage.memory import InMemoryAdapter
from qotd.usecases.adjust_score import (
    ProcessManualScoreEventEmailsConfig,
    process_manual_score_event_emails,
)
from qotd.usecases.publish_game import publish_automated_game
from qotd.usecases.score_submissions import ScoreResponsesConfig, score_responses
from tests.acceptance.harness.mailbox import InMemoryMailbox


@pytest.mark.requirements("6.3", "6.7", "6.22", "6.23")
def test_player_submission_and_organizer_instruction_are_processed_by_their_own_workflows() -> None:
    """Player Submissions and Organizer Instructions stay inside their Requirements Boundaries."""

    game_day = date(2026, 8, 10)
    state = InMemoryAdapter()
    publish_automated_game(
        state=state,
        game_day=game_day,
        question=Question(
            game_date=game_day.isoformat(),
            prompt="Which option is correct?",
            options={"A": "One", "B": "Two", "C": "Three", "D": "Four"},
            correct_option="A",
            source_note="Acceptance fixture",
            source_url="https://example.com/source",
        ),
        message_id="question-message",
        published_at=datetime(2026, 8, 10, 18, tzinfo=UTC),
    )
    player_submission = ParsedEmailMessage(
        message_id="player-submission",
        thread_id="question-thread",
        sender_email="player@example.com",
        subject="Re: QOTD - 08-10-26",
        sent_at=datetime(2026, 8, 10, 20, tzinfo=UTC),
        body_text="A",
    )
    organizer_instruction = ParsedEmailMessage(
        message_id="organizer-instruction",
        thread_id="instruction-thread",
        sender_email="organizer@example.com",
        subject="QOTD score correction",
        sent_at=datetime(2026, 8, 11, 14, tzinfo=UTC),
        body_text=(
            "Action: record-score-event\n"
            "Player: corrected@example.com\n"
            "Day: 2026-08-10\n"
            "Points: 1\n"
            "Reason: organizer correction"
        ),
    )
    inbox = InMemoryMailbox([player_submission, organizer_instruction])

    scoring_result = score_responses(
        ScoreResponsesConfig(
            scoring_date=date(2026, 8, 11),
            game_date=game_day,
            sender="qotd@example.com",
            organizer="organizer@example.com",
            gmail_user="qotd@example.com",
            oauth_client_id="client",
            oauth_client_secret="secret",
            oauth_refresh_token="token",
            state_store=state,
            dry_run=True,
        ),
        fetch_messages=inbox.search,
    )

    assert scoring_result.reply_count == 1
    assert [reply.gmail_message_id for reply in scoring_result.scoring.correct] == ["player-submission"]
    assert {submission.source_message_key for submission in state.submissions.values()} == {
        gmail_message_key("player-submission")
    }
    assert state.instructions == {}
    assert inbox.unread == {"player-submission", "organizer-instruction"}

    instruction_result = process_manual_score_event_emails(
        ProcessManualScoreEventEmailsConfig(
            sender="qotd@example.com",
            gmail_user="qotd@example.com",
            organizer_emails=("organizer@example.com",),
            oauth_client_id="client",
            oauth_client_secret="secret",
            oauth_refresh_token="token",
            state_store=state,
        ),
        fetch_messages=inbox.search,
        send_message=inbox.send,
        mark_message_handled=inbox.mark_read,
    )

    assert [result.message_id for result in instruction_result.processed] == ["organizer-instruction"]
    assert instruction_result.processed[0].status == "applied"
    assert {instruction.source_message_key for instruction in state.instructions.values()} == {
        gmail_message_key("organizer-instruction")
    }
    assert len(state.submissions) == 1
    assert len(state.score_events) == 2
    assert inbox.unread == {"player-submission"}
