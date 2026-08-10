"""Deliver canonical outbound-message intents exactly once."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage

from qotd.domain.canonical import OUTBOUND_PENDING, OUTBOUND_SENT, OutboundMessage, gmail_message_key
from qotd.external.email.core import ParsedEmailMessage
from qotd.external.storage.canonical import CanonicalState


MessageFetcher = Callable[[str], list[ParsedEmailMessage]]
MessageSender = Callable[[EmailMessage], str]


def deliver_outbound_message(
    *, state: CanonicalState, intent: OutboundMessage, sender: str,
    fetch_messages: MessageFetcher, send_message: MessageSender, is_new: bool,
) -> str:
    """Send a newly committed intent or reconcile an older pending intent."""

    if intent.status == OUTBOUND_SENT:
        return intent.source_message_key or intent.id
    if intent.status != OUTBOUND_PENDING:
        raise RuntimeError("Outbound Message has an unknown status")
    if not is_new:
        window_ends_at = intent.created_at + timedelta(days=1)
        after = intent.created_at.strftime("%Y/%m/%d")
        before = (window_ends_at + timedelta(days=1)).strftime("%Y/%m/%d")
        matches = [
            message
            for message in fetch_messages(
                f'in:sent to:{intent.recipient} after:{after} before:{before} subject:"{intent.subject}"'
            )
            if (
                message.subject == intent.subject
                and message.body_text.strip() == intent.body_text.strip()
                and (message.sent_at is None or intent.created_at <= message.sent_at <= window_ends_at)
            )
        ]
        if len(matches) != 1:
            raise RuntimeError("Pending outbound message could not be uniquely reconciled; it remains pending")
        message_id = matches[0].message_id
        sent_at = matches[0].sent_at or datetime.now(UTC)
    else:
        message = EmailMessage()
        message["To"] = intent.recipient
        message["From"] = sender
        message["Subject"] = intent.subject
        if intent.message_type == "question_publication":
            message["Reply-To"] = sender
        message.set_content(intent.body_text)
        message_id = send_message(message)
        sent_at = datetime.now(UTC)
    state.reconcile_outbound_message(
        idempotency_key=intent.idempotency_key,
        source_message_key=gmail_message_key(message_id),
        sent_at=sent_at,
    )
    return message_id
