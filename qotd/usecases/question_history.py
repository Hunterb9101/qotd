"""Shared queries for persisted QOTD question history."""

from __future__ import annotations

from datetime import date

from qotd.domain.models import StoredQuestion
from qotd.external.storage.core import StorageClient


def find_question_for_game_date(state_store: StorageClient, game_date: date) -> StoredQuestion | None:
    """Return the latest stored question and correct-answer update for a game date."""

    game_date_text = game_date.isoformat()
    matches = [
        StoredQuestion.from_record(record)
        for record in state_store.read_question_records()
        if record.get("game_date") == game_date_text
    ]
    if not matches:
        return None

    question = matches[-1]
    updates = state_store.read_correct_answer_updates(game_date=game_date_text)
    if not updates:
        return question

    latest = updates[-1]
    return StoredQuestion(
        game_date=question.game_date,
        prompt=question.prompt,
        options=question.options,
        correct_option=str(latest["correct_option"]),
        source_note=question.source_note,
        source_url=str(latest["source_url"]),
        source=question.source,
        gmail_message_id=question.gmail_message_id,
        created_at=question.created_at,
    )


def load_question_for_game_date(state_store: StorageClient, game_date: date) -> StoredQuestion:
    """Load a stored question for a game date or raise when none exists."""

    question = find_question_for_game_date(state_store, game_date)
    if question is None:
        raise RuntimeError(f"No stored QOTD question found for {game_date.isoformat()}")
    return question


def find_latest_answered_question_before(
    state_store: StorageClient,
    game_date: date,
) -> StoredQuestion | None:
    """Return the most recent earlier question with a displayable answer."""

    cutoff = game_date.isoformat()
    earlier_dates = sorted(
        {
            str(record["game_date"])
            for record in state_store.read_question_records()
            if str(record.get("game_date", "")) < cutoff
        },
        reverse=True,
    )
    for earlier_date in earlier_dates:
        question = find_question_for_game_date(state_store, date.fromisoformat(earlier_date))
        if question is not None and question.correct_option in question.options:
            return question
    return None
