"""Email composition helpers for QOTD messages."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from email.message import EmailMessage

from qotd.domain.dates import is_final_weekday_of_month, question_subject
from qotd.domain.models import OPTION_LABELS, ScoreboardLine, Question, StoredQuestion
from qotd.presentation.rendering import render_template


def build_player_email(
    question: Question,
    sender: str,
    recipients: Sequence[str] = (),
    *,
    delivery_address: str | None = None,
    previous_question: StoredQuestion | None = None,
    point_earners: Sequence[str] = (),
    standings: Sequence[ScoreboardLine] = (),
) -> EmailMessage:
    """Build the Player-facing QOTD email without Answer metadata."""

    if not delivery_address and not recipients:
        raise ValueError("Player email must have a delivery address")

    message = EmailMessage()
    if delivery_address:
        message["To"] = delivery_address
        message["Reply-To"] = sender
    else:
        message["To"] = sender
        message["Bcc"] = ", ".join(recipients)
    message["From"] = sender
    message["Subject"] = question_subject(question.game_date)
    is_month_end_recap = (
        previous_question is not None
        and is_final_weekday_of_month(date.fromisoformat(previous_question.game_date))
    )
    max_points = max((score.points for score in standings), default=None)
    monthly_winners = tuple(
        score
        for score in standings
        if is_month_end_recap and max_points is not None and score.points == max_points
    )
    message.set_content(
        render_template(
            "player_email.txt.j2",
            is_month_end_recap=is_month_end_recap,
            monthly_winners=monthly_winners,
            option_labels=OPTION_LABELS,
            point_earners=point_earners,
            previous_question=previous_question,
            question=question,
            standings=standings,
        )
    )
    return message


def build_organizer_email(*, sender: str, organizer: str, subject: str, body: str) -> EmailMessage:
    """Build an organizer-only email."""

    message = EmailMessage()
    message["To"] = organizer
    message["From"] = sender
    message["Subject"] = subject
    message.set_content(body)
    return message
