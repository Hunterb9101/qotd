"""Date helpers for QOTD game-day windows."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo


MOUNTAIN_TIME = ZoneInfo("America/Denver")
ANSWER_CUTOFF_TIME = time(hour=7, minute=0, tzinfo=MOUNTAIN_TIME)


def is_weekday(value: date) -> bool:
    """Return whether a date is a weekday QOTD game day."""

    return value.weekday() < 5


def previous_game_day(scoring_date: date) -> date:
    """Return the previous weekday game date for a scoring date."""

    candidate = scoring_date - timedelta(days=1)
    while not is_weekday(candidate):
        candidate -= timedelta(days=1)
    return candidate


def next_scoring_day(game_date: date) -> date:
    """Return the next weekday scoring date for a game date."""

    candidate = game_date + timedelta(days=1)
    while not is_weekday(candidate):
        candidate += timedelta(days=1)
    return candidate


def answer_cutoff_at(scoring_date: date) -> datetime:
    """Return the Mountain-time answer cutoff for a scoring date."""

    return datetime.combine(scoring_date, ANSWER_CUTOFF_TIME)


def monthly_series(game_date: date) -> str:
    """Return the MMYY score series for a game date."""

    return game_date.strftime("%m%y")


def is_final_weekday_of_month(value: date) -> bool:
    """Return whether a date is the final weekday in its month."""

    candidate = value + timedelta(days=1)
    while candidate.month == value.month:
        if is_weekday(candidate):
            return False
        candidate += timedelta(days=1)
    return is_weekday(value)
