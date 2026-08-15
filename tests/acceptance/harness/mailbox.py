"""Stateful mailbox behavior for acceptance scenarios."""

from __future__ import annotations

from email.message import EmailMessage
import re

from qotd.external.email.core import ParsedEmailMessage


class InMemoryMailbox:
    """Record unread messages and apply the Gmail predicates used by QOTD."""

    def __init__(self, messages: list[ParsedEmailMessage] | None = None) -> None:
        self.messages = messages or []
        self.unread = {message.message_id for message in self.messages}
        self.sent: list[EmailMessage] = []

    def search(self, query: str) -> list[ParsedEmailMessage]:
        matches = list(self.messages)
        sender = re.search(r"(?:^|\s)from:([^\s]+)", query)
        if sender:
            matches = [message for message in matches if message.sender_email == sender.group(1)]
        subject = re.search(r'subject:"([^"]+)"', query)
        if subject:
            matches = [message for message in matches if subject.group(1) in message.subject]
        if "is:unread" in query:
            matches = [message for message in matches if message.message_id in self.unread]
        return matches

    def send(self, message: EmailMessage) -> str:
        self.sent.append(message)
        return f"sent-{len(self.sent)}"

    def mark_read(self, message_id: str) -> None:
        self.unread.discard(message_id)
