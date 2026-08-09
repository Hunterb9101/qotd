"""Publish canonical Games through manual and automated transitions."""

from __future__ import annotations

import calendar
from datetime import date, datetime

from qotd.domain.canonical import GAME_PENDING, PUBLICATION_AUTOMATED, PUBLICATION_MANUAL, Game, OutboundMessage, new_id
from qotd.domain.dates import answer_cutoff_at, next_scoring_day, question_subject
from qotd.domain.models import Question
from qotd.external.storage.canonical import CanonicalState


def publish_manual_game(
    *, state: CanonicalState, game_day: date, question: Question, message_id: str, published_at: datetime,
    outbound_message: OutboundMessage | None = None,
) -> Game:
    """Publish a manual Game, retaining a pending Answer for the same Day."""

    return state.publish_game(
        _publication_game(
            state=state,
            game_day=game_day,
            question=question,
            publication_mode=PUBLICATION_MANUAL,
            message_id=message_id,
            published_at=published_at,
        ), outbound_message=outbound_message
    )


def publish_automated_game(
    *, state: CanonicalState, game_day: date, question: Question, message_id: str, published_at: datetime,
    outbound_message: OutboundMessage | None = None,
) -> Game:
    """Discard a stale pending manual Game before automated publication."""

    return state.replace_pending_game(
        _publication_game(
            state=state,
            game_day=game_day,
            question=question,
            publication_mode=PUBLICATION_AUTOMATED,
            message_id=message_id,
            published_at=published_at,
        ), outbound_message=outbound_message
    )


def _publication_game(
    *,
    state: CanonicalState,
    game_day: date,
    question: Question,
    publication_mode: str,
    message_id: str,
    published_at: datetime,
) -> Game:
    days_in_month = calendar.monthrange(game_day.year, game_day.month)[1]
    series = state.create_or_find_series(
        name=game_day.strftime("%Y-%m"),
        starts_on=game_day.replace(day=1),
        ends_on=game_day.replace(day=days_in_month),
    )
    return Game(
        id=new_id(),
        series_id=series.id,
        day=game_day,
        status=GAME_PENDING,
        publication_mode=publication_mode,
        question_prompt=question.prompt,
        question_options=question.options,
        publication_subject=question_subject(game_day),
        published_at=published_at,
        publication_message_key=message_id,
        deadline_at=answer_cutoff_at(next_scoring_day(game_day)),
        correct_option=question.correct_option if publication_mode == PUBLICATION_AUTOMATED else None,
        answer_source_url=question.source_url if publication_mode == PUBLICATION_AUTOMATED else None,
        answer_source_note=question.source_note if publication_mode == PUBLICATION_AUTOMATED else None,
        created_at=published_at,
        updated_at=published_at,
    )
