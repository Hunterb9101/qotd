"""Publish canonical Games through manual and automated transitions."""

from __future__ import annotations

import calendar
from datetime import date, datetime

from qotd.domain.canonical import GAME_PUBLISHED, PUBLICATION_AUTOMATED, PUBLICATION_MANUAL, Game, OutboundMessage, Series, new_id
from qotd.domain.dates import answer_cutoff_at, next_scoring_day, question_subject
from qotd.domain.models import Question
from qotd.external.storage.canonical import CanonicalState


def publish_manual_game(
    *, state: CanonicalState, game_day: date, question: Question, message_id: str, published_at: datetime,
    outbound_message: OutboundMessage | None = None, game_id: str | None = None,
) -> Game:
    """Publish a manual Game, retaining a pending Answer for the same Day."""

    series = _publication_series(game_day, created_at=published_at)
    return state.publish_game(
        _publication_game(
            game_day=game_day,
            question=question,
            publication_mode=PUBLICATION_MANUAL,
            game_id=game_id,
            message_id=message_id,
            published_at=published_at,
            series=series,
        ), series=series, outbound_message=outbound_message
    )


def publish_automated_game(
    *, state: CanonicalState, game_day: date, question: Question, message_id: str, published_at: datetime,
    outbound_message: OutboundMessage | None = None, game_id: str | None = None,
) -> Game:
    """Discard a stale pending manual Game before automated publication."""

    series = _publication_series(game_day, created_at=published_at)
    return state.replace_pending_game(
        _publication_game(
            game_day=game_day,
            question=question,
            publication_mode=PUBLICATION_AUTOMATED,
            game_id=game_id,
            message_id=message_id,
            published_at=published_at,
            series=series,
        ), series=series, outbound_message=outbound_message
    )


def _publication_series(game_day: date, *, created_at: datetime) -> Series:
    """Build the Game Day's Series record for the publication transaction."""

    days_in_month = calendar.monthrange(game_day.year, game_day.month)[1]
    return Series(
        id=new_id(), name=game_day.strftime("%Y-%m"), starts_on=game_day.replace(day=1),
        ends_on=game_day.replace(day=days_in_month), created_at=created_at, updated_at=created_at,
    )


def _publication_game(
    *,
    game_day: date,
    question: Question,
    publication_mode: str,
    game_id: str | None = None,
    message_id: str,
    published_at: datetime,
    series: Series,
) -> Game:
    return Game(
        id=game_id or new_id(),
        series_id=series.id,
        day=game_day,
        status=GAME_PUBLISHED,
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
