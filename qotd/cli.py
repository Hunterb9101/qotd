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
    send_parser.add_argument("--delegated-user", default=os.environ.get("QOTD_DELEGATED_USER", "***SECRET***"))
    send_parser.add_argument("--service-account-file", default=os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"))
    send_parser.add_argument("--state-path", type=Path, default=Path(os.environ.get("QOTD_STATE_PATH", DEFAULT_STATE_PATH)))
    send_parser.add_argument("--dry-run", action="store_true")
    return parser


def main() -> None:
    """Run the selected command."""

    parser = build_parser()
    args = parser.parse_args()

    if args.command == "send-question":
        service_account_file = args.service_account_file or ""
        if not service_account_file and not args.dry_run_recipient:
            service_account_file = env_value("GOOGLE_APPLICATION_CREDENTIALS")

        result = send_question(
            SendQuestionConfig(
                game_date=args.date,
                sender=args.sender,
                contact_group_name=args.contact_group_name,
                state_path=args.state_path,
                delegated_user=args.delegated_user,
                service_account_file=service_account_file,
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
