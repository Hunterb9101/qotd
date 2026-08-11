"""Production Gmail and email-rendering wiring for QOTD workflows."""

from qotd.external.email.gmail import GmailAdapter, mark_gmail_message_read, search_messages, send_gmail_message
from qotd.presentation.emails import build_organizer_email, build_player_email
from qotd.presentation.organizer_updates import build_organizer_update_body

__all__ = [
    "build_organizer_email",
    "build_organizer_update_body",
    "build_player_email",
    "GmailAdapter",
    "mark_gmail_message_read",
    "search_messages",
    "send_gmail_message",
]
