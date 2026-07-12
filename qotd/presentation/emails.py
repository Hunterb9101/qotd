"""Email composition helpers for QOTD messages."""

from __future__ import annotations

from collections.abc import Sequence
from email.message import EmailMessage

from qotd.domain.dates import question_subject
from qotd.domain.models import OPTION_LABELS, Question, StoredQuestion
from qotd.presentation.rendering import render_template


def build_participant_email(
    question: Question,
    sender: str,
    recipients: Sequence[str],
    *,
    previous_question: StoredQuestion | None = None,
) -> EmailMessage:
    """Build the participant-facing QOTD email without answer metadata."""

    if not recipients:
        raise ValueError("participant email must have at least one recipient")

    message = EmailMessage()
    message["To"] = sender
    message["Bcc"] = ", ".join(recipients)
    message["From"] = sender
    message["Subject"] = question_subject(question.game_date)
    message.set_content(
        render_template(
            "participant_email.txt.j2",
            option_labels=OPTION_LABELS,
            previous_question=previous_question,
            question=question,
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
