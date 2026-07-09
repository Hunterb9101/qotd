"""CLI for QOTD workflows."""

from __future__ import annotations

import argparse
import os
from datetime import date

from qotd.response_workflow import ScoreResponsesConfig, score_responses, today_mountain
from qotd.state_factory import build_bigquery_state_store
from qotd.workflow import SendQuestionConfig, send_question


DEFAULT_CONTACT_GROUP_NAME = "QOTD Participants"
DEFAULT_BIGQUERY_DATASET = "qotd"


def parse_date(value: str) -> date:
    """Parse an ISO date argument."""

    return date.fromisoformat(value)


def env_value(name: str, fallback: str | None = None) -> str:
    """Read a required environment variable or return a fallback."""

    value = os.environ.get(name, fallback)
    if not value:
        raise SystemExit(f"Missing required environment variable: {name}")
    return value


def add_google_options(parser: argparse.ArgumentParser) -> None:
    """Add shared Google OAuth and BigQuery options."""

    parser.add_argument("--oauth-client-id", default=os.environ.get("GOOGLE_OAUTH_CLIENT_ID", ""))
    parser.add_argument("--oauth-client-secret", default=os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET", ""))
    parser.add_argument("--oauth-refresh-token", default=os.environ.get("GOOGLE_OAUTH_REFRESH_TOKEN", ""))
    parser.add_argument("--google-cloud-project", default=os.environ.get("GOOGLE_CLOUD_PROJECT", ""))
    parser.add_argument("--bigquery-dataset", default=os.environ.get("BIGQUERY_DATASET", DEFAULT_BIGQUERY_DATASET))


def require_google_options(args: argparse.Namespace) -> None:
    """Require Google OAuth and BigQuery settings."""

    if not args.oauth_client_id:
        args.oauth_client_id = env_value("GOOGLE_OAUTH_CLIENT_ID")
    if not args.oauth_client_secret:
        args.oauth_client_secret = env_value("GOOGLE_OAUTH_CLIENT_SECRET")
    if not args.oauth_refresh_token:
        args.oauth_refresh_token = env_value("GOOGLE_OAUTH_REFRESH_TOKEN")
    if not args.google_cloud_project:
        args.google_cloud_project = env_value("GOOGLE_CLOUD_PROJECT")
    if not args.bigquery_dataset:
        args.bigquery_dataset = env_value("BIGQUERY_DATASET", DEFAULT_BIGQUERY_DATASET)


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
    add_google_options(send_parser)
    send_parser.add_argument("--dry-run", action="store_true")

    score_parser = subparsers.add_parser("score-responses", help="Collect and score QOTD replies")
    score_parser.add_argument("--scoring-date", type=parse_date, default=None)
    score_parser.add_argument("--sender", default=os.environ.get("QOTD_SENDER", "***SECRET***"))
    score_parser.add_argument("--organizer", default=os.environ.get("QOTD_ORGANIZER", os.environ.get("QOTD_SENDER", "***SECRET***")))
    score_parser.add_argument("--gmail-user", default=os.environ.get("QOTD_GMAIL_USER", os.environ.get("QOTD_SENDER", "***SECRET***")))
    add_google_options(score_parser)
    score_parser.add_argument("--dry-run", action="store_true")
    return parser


def main() -> None:
    """Run the selected command."""

    parser = build_parser()
    args = parser.parse_args()

    if args.command == "send-question":
        require_google_options(args)
        state_store = build_bigquery_state_store(
            project_id=args.google_cloud_project,
            dataset=args.bigquery_dataset,
            oauth_client_id=args.oauth_client_id,
            oauth_client_secret=args.oauth_client_secret,
            oauth_refresh_token=args.oauth_refresh_token,
        )

        send_result = send_question(
            SendQuestionConfig(
                game_date=args.date,
                sender=args.sender,
                contact_group_name=args.contact_group_name,
                state_store=state_store,
                gmail_user=args.gmail_user,
                oauth_client_id=args.oauth_client_id,
                oauth_client_secret=args.oauth_client_secret,
                oauth_refresh_token=args.oauth_refresh_token,
                participant_emails=tuple(args.dry_run_recipient),
                dry_run=args.dry_run,
            )
        )
        print(
            f"Stored question for {send_result.record.game_date}: "
            f"{send_result.record.gmail_message_id} ({send_result.recipient_count} recipients)"
        )
        if args.dry_run:
            print()
            print(send_result.email_body)

    elif args.command == "score-responses":
        require_google_options(args)
        state_store = build_bigquery_state_store(
            project_id=args.google_cloud_project,
            dataset=args.bigquery_dataset,
            oauth_client_id=args.oauth_client_id,
            oauth_client_secret=args.oauth_client_secret,
            oauth_refresh_token=args.oauth_refresh_token,
        )

        score_result = score_responses(
            ScoreResponsesConfig(
                scoring_date=args.scoring_date or today_mountain(),
                sender=args.sender,
                organizer=args.organizer,
                gmail_user=args.gmail_user,
                oauth_client_id=args.oauth_client_id,
                oauth_client_secret=args.oauth_client_secret,
                oauth_refresh_token=args.oauth_refresh_token,
                state_store=state_store,
                dry_run=args.dry_run,
            )
        )
        print(
            f"Scored {score_result.reply_count} replies for {score_result.question.game_date}; "
            f"organizer update {score_result.organizer_message_id}"
        )
        if args.dry_run:
            print()
            print(score_result.organizer_update_body)
