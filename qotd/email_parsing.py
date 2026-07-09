"""Email parsing helpers for QOTD questions and replies."""

from __future__ import annotations

import base64
import html
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from email.header import decode_header, make_header
from email.message import Message
from email.utils import parseaddr, parsedate_to_datetime
from html.parser import HTMLParser
from typing import Any

from qotd.contacts import normalize_email_addresses


ON_WROTE_RE = re.compile(r"^On .+ wrote:$")
REPLY_HEADER_RE = re.compile(r"^-+Original Message-+$", re.IGNORECASE)
MESSAGE_ID_FALLBACK = "unknown"


@dataclass(frozen=True)
class ParsedEmailMessage:
    """Normalized email message data."""

    message_id: str
    thread_id: str
    sender_email: str
    subject: str
    sent_at: datetime | None
    body_text: str


@dataclass(frozen=True)
class ReplyCandidate:
    """Reply data that can later be interpreted and scored."""

    game_date: str
    sender_email: str
    gmail_message_id: str
    received_at: str
    body_text: str

    @property
    def processing_key(self) -> str:
        """Return an idempotency key for this sender and game date."""

        return f"{self.game_date}:{self.sender_email}"


class HTMLToText(HTMLParser):
    """Small HTML-to-text converter for Gmail message bodies."""

    BLOCK_TAGS = {"br", "div", "p", "li", "tr", "table"}

    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Insert light spacing for block tags."""

        if tag.lower() in self.BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        """Collect visible text."""

        self._parts.append(data)

    def text(self) -> str:
        """Return normalized text."""

        return html.unescape("".join(self._parts))


def decode_subject(raw_subject: str | None) -> str:
    """Decode an RFC 2047 encoded email subject."""

    if not raw_subject:
        return ""
    return str(make_header(decode_header(raw_subject)))


def message_datetime(message: Message) -> datetime | None:
    """Parse a message date, returning None when the header is invalid."""

    raw_date = message.get("Date")
    if not raw_date:
        return None
    try:
        return parsedate_to_datetime(raw_date)
    except (TypeError, ValueError):
        return None


def decode_part(part: Message) -> str:
    """Decode one text email part."""

    payload = part.get_payload(decode=True)
    if payload is None:
        raw_payload = part.get_payload()
        if isinstance(raw_payload, str):
            text = raw_payload
        else:
            return ""
    elif isinstance(payload, bytes):
        charset = part.get_content_charset() or "utf-8"
        text = payload.decode(charset, errors="replace")
    else:
        return ""

    if part.get_content_type() == "text/html":
        parser = HTMLToText()
        parser.feed(text)
        return parser.text()
    return text


def message_body_text(message: Message) -> str:
    """Return the preferred plain text body for a message."""

    text_parts: list[tuple[str, str]] = []
    if message.is_multipart():
        for part in message.walk():
            if part.get_content_maintype() == "multipart":
                continue
            content_type = part.get_content_type()
            if content_type in {"text/plain", "text/html"}:
                text_parts.append((content_type, decode_part(part)))
    elif message.get_content_type() in {"text/plain", "text/html"}:
        text_parts.append((message.get_content_type(), decode_part(message)))

    for content_type, text in text_parts:
        if content_type == "text/plain" and text.strip():
            return text
    return text_parts[0][1] if text_parts else ""


def clean_message_text(text: str) -> str:
    """Normalize body text and remove quoted reply material."""

    lines: list[str] = []
    for raw_line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = re.sub(r"\s+", " ", raw_line).strip()
        if not line:
            continue
        if line.startswith(">"):
            continue
        if ON_WROTE_RE.match(line) or REPLY_HEADER_RE.match(line):
            break
        if line in {"[image: image.png]", "[image.png]"}:
            continue
        lines.append(line)
    return "\n".join(lines)


def parse_rfc822_message(message: Message, *, fallback_message_id: str = MESSAGE_ID_FALLBACK) -> ParsedEmailMessage:
    """Parse a standard library email message into normalized QOTD fields."""

    sender_email = parseaddr(message.get("From", ""))[1].lower()
    return ParsedEmailMessage(
        message_id=message.get("Message-ID", fallback_message_id).strip() or fallback_message_id,
        thread_id=message.get("Thread-ID", ""),
        sender_email=sender_email,
        subject=decode_subject(message.get("Subject")),
        sent_at=message_datetime(message),
        body_text=clean_message_text(message_body_text(message)),
    )


def _urlsafe_b64decode(value: str) -> bytes:
    """Decode Gmail's URL-safe base64 payload format."""

    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(f"{value}{padding}")


def _gmail_payload_text(payload: dict[str, Any]) -> str:
    """Extract preferred text from a Gmail API payload."""

    mime_type = payload.get("mimeType")
    body = payload.get("body", {})
    data = body.get("data")
    if isinstance(data, str) and mime_type in {"text/plain", "text/html"}:
        text = _urlsafe_b64decode(data).decode("utf-8", errors="replace")
        if mime_type == "text/html":
            parser = HTMLToText()
            parser.feed(text)
            return parser.text()
        return text

    parts = payload.get("parts", [])
    text_parts: list[tuple[str, str]] = []
    if isinstance(parts, list):
        for part in parts:
            if isinstance(part, dict):
                part_text = _gmail_payload_text(part)
                part_mime_type = part.get("mimeType", "")
                if part_text and part_mime_type in {"text/plain", "text/html"}:
                    text_parts.append((part_mime_type, part_text))
                elif part_text:
                    text_parts.append(("", part_text))

    for part_mime_type, part_text in text_parts:
        if part_mime_type == "text/plain" and part_text.strip():
            return part_text
    return text_parts[0][1] if text_parts else ""


def parse_gmail_message(message: dict[str, Any]) -> ParsedEmailMessage:
    """Parse a Gmail API message resource into normalized QOTD fields."""

    headers = {
        header.get("name", "").lower(): header.get("value", "")
        for header in message.get("payload", {}).get("headers", [])
        if isinstance(header, dict)
    }
    sender_email = parseaddr(headers.get("from", ""))[1].lower()
    raw_internal_date = message.get("internalDate")
    sent_at: datetime | None = None
    if isinstance(raw_internal_date, str) and raw_internal_date.isdigit():
        sent_at = datetime.fromtimestamp(int(raw_internal_date) / 1000, tz=UTC)

    return ParsedEmailMessage(
        message_id=str(message.get("id") or headers.get("message-id") or MESSAGE_ID_FALLBACK),
        thread_id=str(message.get("threadId") or ""),
        sender_email=sender_email,
        subject=decode_subject(headers.get("subject")),
        sent_at=sent_at,
        body_text=clean_message_text(_gmail_payload_text(message.get("payload", {}))),
    )


def build_reply_candidate(message: ParsedEmailMessage, *, game_date: str) -> ReplyCandidate:
    """Build a reply candidate for later interpretation and scoring."""

    normalized_email = normalize_email_addresses([message.sender_email])
    if not normalized_email:
        raise ValueError("reply message is missing a sender email")
    return ReplyCandidate(
        game_date=game_date,
        sender_email=normalized_email[0],
        gmail_message_id=message.message_id,
        received_at=message.sent_at.isoformat() if message.sent_at else "",
        body_text=message.body_text,
    )
