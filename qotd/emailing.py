"""Email composition and Gmail API delivery."""

from __future__ import annotations

import base64
import importlib
from collections.abc import Sequence
from email.message import EmailMessage

from qotd.models import OPTION_LABELS, Question

GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"


def build_participant_email(question: Question, sender: str, recipients: Sequence[str]) -> EmailMessage:
    """Build the participant-facing QOTD email without answer metadata."""

    if not recipients:
        raise ValueError("participant email must have at least one recipient")

    message = EmailMessage()
    message["To"] = sender
    message["Bcc"] = ", ".join(recipients)
    message["From"] = sender
    message["Subject"] = f"QOTD - {question.game_date}"
    lines = [
        "Question of the Day",
        "",
        question.prompt,
        "",
    ]
    for label in OPTION_LABELS:
        lines.append(f"{label}. {question.options[label]}")
    lines.extend(["", "Reply with A, B, C, or D."])
    message.set_content("\n".join(lines))
    return message


def encode_gmail_message(message: EmailMessage) -> str:
    """Encode an email message for Gmail API transmission."""

    return base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")


def send_gmail_message(
    message: EmailMessage,
    *,
    delegated_user: str,
    service_account_file: str,
) -> str:
    """Send a message through Gmail API using delegated service-account auth."""

    service_account = importlib.import_module("google.oauth2.service_account")
    discovery = importlib.import_module("googleapiclient.discovery")

    credentials = service_account.Credentials.from_service_account_file(
        service_account_file,
        scopes=[GMAIL_SEND_SCOPE],
    ).with_subject(delegated_user)
    service = discovery.build("gmail", "v1", credentials=credentials, cache_discovery=False)
    response = (
        service.users()
        .messages()
        .send(userId=delegated_user, body={"raw": encode_gmail_message(message)})
        .execute()
    )
    message_id = response.get("id")
    if not message_id:
        raise RuntimeError("Gmail API response did not include a message id")
    return str(message_id)
