"""Gmail API email adapter."""

from __future__ import annotations

import base64
import html
import importlib
import re
from datetime import UTC, datetime
from email.header import decode_header, make_header
from email.message import EmailMessage
from email.utils import parseaddr, parsedate_to_datetime
from html.parser import HTMLParser
from typing import Any

from qotd.domain.contacts import normalize_email_addresses
from qotd.domain.models import ReplyCandidate
from qotd.external.auth.gcp import build_oauth_credentials
from qotd.external.email.core import EmailClient, ParsedEmailMessage


GMAIL_READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"
ON_WROTE_RE = re.compile(r"^On .+ wrote:$")
REPLY_HEADER_RE = re.compile(r"^-+Original Message-+$", re.IGNORECASE)
MESSAGE_ID_FALLBACK = "unknown"


class _HTMLToText(HTMLParser):
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


def build_gmail_service(
    *,
    oauth_client_id: str,
    oauth_client_secret: str,
    oauth_refresh_token: str,
    scopes: list[str] | None = None,
) -> Any:
    """Build a Gmail API service."""

    discovery = importlib.import_module("googleapiclient.discovery")
    credentials = build_oauth_credentials(
        client_id=oauth_client_id,
        client_secret=oauth_client_secret,
        refresh_token=oauth_refresh_token,
        scopes=scopes or [GMAIL_READONLY_SCOPE],
    )
    return discovery.build("gmail", "v1", credentials=credentials, cache_discovery=False)


def list_message_ids(service: Any, *, user_id: str, query: str, max_results: int = 100) -> list[str]:
    """List Gmail message ids matching a search query."""

    message_ids: list[str] = []
    request = service.users().messages().list(userId=user_id, q=query, maxResults=max_results)
    while request is not None:
        response = request.execute()
        for message in response.get("messages", []):
            message_id = message.get("id")
            if isinstance(message_id, str):
                message_ids.append(message_id)
        request = service.users().messages().list_next(request, response)
    return message_ids


def get_message(service: Any, *, user_id: str, message_id: str) -> dict[str, Any]:
    """Fetch one Gmail message in full format."""

    response = (
        service.users()
        .messages()
        .get(userId=user_id, id=message_id, format="full")
        .execute()
    )
    if not isinstance(response, dict):
        raise RuntimeError(f"Gmail message response was not an object: {message_id}")
    return response


def encode_gmail_message(message: EmailMessage) -> str:
    """Encode an email message for Gmail API transmission."""

    return base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")


def search_messages(
    *,
    user_id: str,
    oauth_client_id: str,
    oauth_client_secret: str,
    oauth_refresh_token: str,
    query: str,
    max_results: int = 100,
) -> list[ParsedEmailMessage]:
    """Search Gmail and return normalized messages."""

    return GmailAdapter.from_oauth(
        oauth_client_id=oauth_client_id,
        oauth_client_secret=oauth_client_secret,
        oauth_refresh_token=oauth_refresh_token,
    ).search_messages(user_id=user_id, query=query, max_results=max_results)


def send_gmail_message(
    message: EmailMessage,
    *,
    user_id: str,
    oauth_client_id: str,
    oauth_client_secret: str,
    oauth_refresh_token: str,
) -> str:
    """Send a message through Gmail API using OAuth user auth."""

    return GmailAdapter.from_oauth(
        oauth_client_id=oauth_client_id,
        oauth_client_secret=oauth_client_secret,
        oauth_refresh_token=oauth_refresh_token,
    ).send_message(message, user_id=user_id)


class GmailAdapter(EmailClient):
    """Gmail API implementation of email sending and search."""

    def __init__(self, *, service: Any) -> None:
        self.service = service

    @classmethod
    def from_oauth(
        cls,
        *,
        oauth_client_id: str,
        oauth_client_secret: str,
        oauth_refresh_token: str,
        scopes: list[str] | None = None,
    ) -> GmailAdapter:
        """Build a Gmail adapter from OAuth user credentials."""

        return cls(
            service=build_gmail_service(
                oauth_client_id=oauth_client_id,
                oauth_client_secret=oauth_client_secret,
                oauth_refresh_token=oauth_refresh_token,
                scopes=scopes or [GMAIL_READONLY_SCOPE, GMAIL_SEND_SCOPE],
            )
        )

    def send_message(self, message: EmailMessage, *, user_id: str) -> str:
        """Send a message through Gmail API."""

        response = (
            self.service.users()
            .messages()
            .send(userId=user_id, body={"raw": encode_gmail_message(message)})
            .execute()
        )
        message_id = response.get("id")
        if not message_id:
            raise RuntimeError("Gmail API response did not include a message id")
        return str(message_id)

    def read_message(self, message: dict[str, Any]) -> ParsedEmailMessage:
        """Read one Gmail API message into normalized email data."""

        return self.parse_gmail_message(message)

    def search_messages(self, *, user_id: str, query: str, max_results: int = 100) -> list[ParsedEmailMessage]:
        """Search Gmail and return normalized messages."""

        return [
            self.read_message(get_message(self.service, user_id=user_id, message_id=message_id))
            for message_id in list_message_ids(
                self.service,
                user_id=user_id,
                query=query,
                max_results=max_results,
            )
        ]

    @staticmethod
    def decode_subject(raw_subject: str | None) -> str:
        """Decode an RFC 2047 encoded email subject."""

        if not raw_subject:
            return ""
        return str(make_header(decode_header(raw_subject)))

    @staticmethod
    def message_datetime(message: EmailMessage) -> datetime | None:
        """Parse a message date, returning None when the header is invalid."""

        raw_date = message.get("Date")
        if not raw_date:
            return None
        try:
            return parsedate_to_datetime(raw_date)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def decode_part(part: EmailMessage) -> str:
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
            parser = _HTMLToText()
            parser.feed(text)
            return parser.text()
        return text

    @classmethod
    def message_body_text(cls, message: EmailMessage) -> str:
        """Return the preferred plain text body for a message."""

        text_parts: list[tuple[str, str]] = []
        if message.is_multipart():
            for part in message.walk():
                if part.get_content_maintype() == "multipart":
                    continue
                content_type = part.get_content_type()
                if content_type in {"text/plain", "text/html"}:
                    text_parts.append((content_type, cls.decode_part(part)))
        elif message.get_content_type() in {"text/plain", "text/html"}:
            text_parts.append((message.get_content_type(), cls.decode_part(message)))

        for content_type, text in text_parts:
            if content_type == "text/plain" and text.strip():
                return text
        return text_parts[0][1] if text_parts else ""

    @staticmethod
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

    @classmethod
    def parse_rfc822_message(
        cls,
        message: EmailMessage,
        *,
        fallback_message_id: str = MESSAGE_ID_FALLBACK,
    ) -> ParsedEmailMessage:
        """Parse a standard library email message into normalized QOTD fields."""

        sender_email = parseaddr(message.get("From", ""))[1].lower()
        return ParsedEmailMessage(
            message_id=message.get("Message-ID", fallback_message_id).strip() or fallback_message_id,
            thread_id=message.get("Thread-ID", ""),
            sender_email=sender_email,
            subject=cls.decode_subject(message.get("Subject")),
            sent_at=cls.message_datetime(message),
            body_text=cls.clean_message_text(cls.message_body_text(message)),
        )

    @staticmethod
    def _urlsafe_b64decode(value: str) -> bytes:
        """Decode Gmail's URL-safe base64 payload format."""

        padding = "=" * (-len(value) % 4)
        return base64.urlsafe_b64decode(f"{value}{padding}")

    @classmethod
    def _gmail_payload_text(cls, payload: dict[str, Any]) -> str:
        """Extract preferred text from a Gmail API payload."""

        mime_type = payload.get("mimeType")
        body = payload.get("body", {})
        data = body.get("data")
        if isinstance(data, str) and mime_type in {"text/plain", "text/html"}:
            text = cls._urlsafe_b64decode(data).decode("utf-8", errors="replace")
            if mime_type == "text/html":
                parser = _HTMLToText()
                parser.feed(text)
                return parser.text()
            return text

        parts = payload.get("parts", [])
        text_parts: list[tuple[str, str]] = []
        if isinstance(parts, list):
            for part in parts:
                if isinstance(part, dict):
                    part_text = cls._gmail_payload_text(part)
                    part_mime_type = part.get("mimeType", "")
                    if part_text and part_mime_type in {"text/plain", "text/html"}:
                        text_parts.append((part_mime_type, part_text))
                    elif part_text:
                        text_parts.append(("", part_text))

        for part_mime_type, part_text in text_parts:
            if part_mime_type == "text/plain" and part_text.strip():
                return part_text
        return text_parts[0][1] if text_parts else ""

    @classmethod
    def parse_gmail_message(cls, message: dict[str, Any]) -> ParsedEmailMessage:
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
            subject=cls.decode_subject(headers.get("subject")),
            sent_at=sent_at,
            body_text=cls.clean_message_text(cls._gmail_payload_text(message.get("payload", {}))),
        )

    @staticmethod
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
