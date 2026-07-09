"""CLI for QOTD workflows."""

from __future__ import annotations

import argparse
import os
from datetime import date
from pathlib import Path

from qotd.workflow import SendQuestionConfig, send_question


DEFAULT_STATE_PATH = Path("state/questions.jsonl")
DEFAULT_CONTACT_GROUP_NAME = "QOTD Participants"


def parse_date(value: str) -> date:
    """Parse an ISO date argument."""

    return date.fromisoformat(value)


def env_value(name: str, fallback: str | None = None) -> str:
    """Read a required environment variable or return a fallback."""

    value = os.environ.get(name, fallback)
    if not value:
        raise SystemExit(f"Missing required environment variable: {name}")
    return value


def build_parser() -> argparse.ArgumentParser:
    """Build the QOTD command parser."""

    parser = argparse.ArgumentParser(prog="qotd")
    subparsers = parser.add_subparsers(dest="command", required=True)

    send_parser = subparsers.add_parser("send-question", help="Generate and send today's QOTD email")
    send_parser.add_argument("--date", type=parse_date, default=date.today())
    send_parser.add_argument("--contact-group-name", default=os.environ.get("QOTD_CONTACT_GROUP_NAME", DEFAULT_CONTACT_GROUP_NAME))
    send_parser.add_argument("--dry-run-recipient", action="append", default=[])
    send_parser.add_argument("--sender", default=os.environ.get("QOTD_SENDER", "***SECRET***"))
    send_parser.add_argument("--gmail-user", default=os.environ.get("QOTD_GMAIL_USER", os.environ.get("QOTD_SENDER", "***SECRET***")))
    send_parser.add_argument("--oauth-client-id", default=os.environ.get("GOOGLE_OAUTH_CLIENT_ID", ""))
    send_parser.add_argument("--oauth-client-secret", default=os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET", ""))
    send_parser.add_argument("--oauth-refresh-token", default=os.environ.get("GOOGLE_OAUTH_REFRESH_TOKEN", ""))
    send_parser.add_argument("--state-path", type=Path, default=Path(os.environ.get("QOTD_STATE_PATH", DEFAULT_STATE_PATH)))
    send_parser.add_argument("--dry-run", action="store_true")
    return parser


def main() -> None:
    """Run the selected command."""

    parser = build_parser()
    args = parser.parse_args()

    if args.command == "send-question":
        if not args.dry_run_recipient:
            if not args.oauth_client_id:
                args.oauth_client_id = env_value("GOOGLE_OAUTH_CLIENT_ID")
            if not args.oauth_client_secret:
                args.oauth_client_secret = env_value("GOOGLE_OAUTH_CLIENT_SECRET")
            if not args.oauth_refresh_token:
                args.oauth_refresh_token = env_value("GOOGLE_OAUTH_REFRESH_TOKEN")

        result = send_question(
            SendQuestionConfig(
                game_date=args.date,
                sender=args.sender,
                contact_group_name=args.contact_group_name,
                state_path=args.state_path,
                gmail_user=args.gmail_user,
                oauth_client_id=args.oauth_client_id,
                oauth_client_secret=args.oauth_client_secret,
                oauth_refresh_token=args.oauth_refresh_token,
                participant_emails=tuple(args.dry_run_recipient),
                dry_run=args.dry_run,
            )
        )
        print(
            f"Stored question for {result.record.game_date}: "
            f"{result.record.gmail_message_id} ({result.recipient_count} recipients)"
        )
        if args.dry_run:
            print()
            print(result.email_body)
