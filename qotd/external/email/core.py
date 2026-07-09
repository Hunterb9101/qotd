"""Implementation-agnostic email client contract."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from email.message import EmailMessage
from typing import Any


@dataclass(frozen=True)
class ParsedEmailMessage:
    """Normalized email message data."""

    message_id: str
    thread_id: str
    sender_email: str
    subject: str
    sent_at: datetime | None
    body_text: str


class EmailClient(ABC):
    """Client interface for sending and receiving email messages."""

    @abstractmethod
    def send_message(self, message: EmailMessage, *, user_id: str) -> str:
        """Send one email message and return the provider message id."""

    @abstractmethod
    def read_message(self, message: Any) -> ParsedEmailMessage:
        """Read one provider message into normalized email data."""

    @abstractmethod
    def search_messages(self, *, user_id: str, query: str, max_results: int = 100) -> list[ParsedEmailMessage]:
        """Search provider messages and return normalized email data."""
