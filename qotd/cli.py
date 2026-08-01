"""CLI for QOTD workflows."""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict
from datetime import date

from qotd.domain.dates import current_game_date
from qotd.external.llm.openai import build_openai_llm_client
from qotd.external.storage.bigquery import build_bigquery_state_store
from qotd.usecases.correct_answer import ProcessCorrectAnswerEmailsConfig, process_correct_answer_emails
from qotd.usecases.adjust_score import (
    ProcessScoreAdjustmentEmailsConfig,
    ScoreAdjustmentConfig,
    apply_score_adjustment,
    process_score_adjustment_emails,
)
from qotd.usecases.score_responses import LLMAnswerInterpreter, ScoreResponsesConfig, score_responses
from qotd.usecases.send_question import SendQuestionConfig, send_question
from qotd.usecases.discover_question_topic_from_web import LLMTopicDiscoverer
from qotd.usecases.repair_generated_question import RepairGeneratedQuestion
from qotd.usecases.generate_question_for_topic import (
    GenerateQuestionSamplesConfig,
    GenerateResearchedQuestionConfig,
    LLMQuestionEvaluator,
    LLMQuestionGenerator,
    generate_question_samples,
    generate_researched_question,
)


DEFAULT_BIGQUERY_DATASET = "qotd"
DEFAULT_OPENAI_INTERPRETER_MODEL = "gpt-4.1-mini"
DEFAULT_OPENAI_GENERATOR_MODEL = "gpt-5.4-mini"
DEFAULT_OPENAI_WEB_SEARCH_MODEL = "gpt-5.4-mini"


def parse_date(value: str) -> date:
    """Parse an ISO date argument."""

    return date.fromisoformat(value)


def nonblank_text(value: str) -> str:
    """Parse a required non-blank text argument."""

    cleaned = value.strip()
    if not cleaned:
        raise argparse.ArgumentTypeError("must not be blank")
    return cleaned


def positive_int(value: str) -> int:
    """Parse an integer greater than zero."""

    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


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


def require_sender_options(args: argparse.Namespace) -> None:
    """Populate email identity options from the required sender setting."""

    sender = args.sender or env_value("QOTD_SENDER")
    args.sender = sender
    if hasattr(args, "gmail_user") and not args.gmail_user:
        args.gmail_user = sender
    if hasattr(args, "organizer") and isinstance(args.organizer, str) and not args.organizer:
        args.organizer = sender


def build_parser() -> argparse.ArgumentParser:
    """Build the QOTD command parser."""

    parser = argparse.ArgumentParser(prog="qotd")
    subparsers = parser.add_subparsers(dest="command", required=True)

    send_parser = subparsers.add_parser("send-question", help="Generate and send today's QOTD email")
    send_parser.add_argument("--date", type=parse_date, default=current_game_date())
    send_parser.add_argument("--google-group-email", default=os.environ.get("QOTD_GOOGLE_GROUP_EMAIL", ""))
    send_parser.add_argument("--sender", default=os.environ.get("QOTD_SENDER", ""))
    send_parser.add_argument("--gmail-user", default=os.environ.get("QOTD_SENDER", ""))
    send_parser.add_argument("--openai-api-key", default=os.environ.get("OPENAI_API_KEY", ""))
    send_parser.add_argument(
        "--openai-generator-model",
        default=os.environ.get("OPENAI_GENERATOR_MODEL", DEFAULT_OPENAI_GENERATOR_MODEL),
    )
    send_parser.add_argument(
        "--openai-web-search-model",
        default=os.environ.get("OPENAI_WEB_SEARCH_MODEL", DEFAULT_OPENAI_WEB_SEARCH_MODEL),
    )
    add_google_options(send_parser)
    send_parser.add_argument("--dry-run", action="store_true")

    samples_parser = subparsers.add_parser(
        "generate-samples",
        help="Generate reviewable question candidates without sending or storing them",
    )
    samples_parser.add_argument("--topic", required=True, type=nonblank_text)
    samples_parser.add_argument("--count", required=True, type=positive_int)
    samples_parser.add_argument("--date", type=parse_date, default=current_game_date())
    samples_parser.add_argument("--category", type=nonblank_text, default="General Knowledge")
    samples_parser.add_argument("--openai-api-key", default=os.environ.get("OPENAI_API_KEY", ""))
    samples_parser.add_argument(
        "--openai-generator-model",
        default=os.environ.get("OPENAI_GENERATOR_MODEL", DEFAULT_OPENAI_GENERATOR_MODEL),
    )
    score_parser = subparsers.add_parser("score-responses", help="Collect and score QOTD replies")
    score_parser.add_argument("--scoring-date", type=parse_date, default=None)
    score_parser.add_argument("--game-date", type=parse_date, default=None)
    score_parser.add_argument("--sender", default=os.environ.get("QOTD_SENDER", ""))
    score_parser.add_argument("--organizer", default=os.environ.get("QOTD_SENDER", ""))
    score_parser.add_argument("--gmail-user", default=os.environ.get("QOTD_SENDER", ""))
    score_parser.add_argument("--openai-api-key", default=os.environ.get("OPENAI_API_KEY", ""))
    score_parser.add_argument(
        "--openai-interpreter-model",
        default=os.environ.get("OPENAI_INTERPRETER_MODEL", DEFAULT_OPENAI_INTERPRETER_MODEL),
    )
    score_parser.add_argument("--disable-ai-answer-interpreter", action="store_true")
    add_google_options(score_parser)
    score_parser.add_argument("--dry-run", action="store_true")

    adjust_parser = subparsers.add_parser("adjust-score", help="Apply a manual score adjustment")
    adjust_parser.add_argument("--email", required=True)
    period_group = adjust_parser.add_mutually_exclusive_group(required=True)
    period_group.add_argument("--date", dest="game_date", type=parse_date)
    period_group.add_argument("--series")
    adjust_parser.add_argument("--points", dest="points_delta", type=int, required=True)
    adjust_parser.add_argument("--reason", required=True)
    adjust_parser.add_argument("--gmail-message-id", default="")
    adjust_parser.add_argument("--idempotency-key", default=None)
    add_google_options(adjust_parser)
    adjust_parser.add_argument("--dry-run", action="store_true")

    email_adjust_parser = subparsers.add_parser(
        "process-score-adjustments",
        help="Process score adjustment request emails",
    )
    email_adjust_parser.add_argument("--sender", default=os.environ.get("QOTD_SENDER", ""))
    email_adjust_parser.add_argument("--gmail-user", default=os.environ.get("QOTD_SENDER", ""))
    email_adjust_parser.add_argument("--organizer", action="append", default=[])
    email_adjust_parser.add_argument("--query", default='is:unread "Action: adjust-score"')
    email_adjust_parser.add_argument("--max-results", type=int, default=25)
    add_google_options(email_adjust_parser)
    email_adjust_parser.add_argument("--dry-run", action="store_true")

    correct_answer_parser = subparsers.add_parser(
        "process-correct-answers",
        help="Process manual correct-answer emails",
    )
    correct_answer_parser.add_argument("--sender", default=os.environ.get("QOTD_SENDER", ""))
    correct_answer_parser.add_argument("--gmail-user", default=os.environ.get("QOTD_SENDER", ""))
    correct_answer_parser.add_argument("--organizer", action="append", default=[])
    correct_answer_parser.add_argument("--query", default='is:unread "Action: set-correct-answer"')
    correct_answer_parser.add_argument("--max-results", type=int, default=25)
    add_google_options(correct_answer_parser)
    correct_answer_parser.add_argument("--dry-run", action="store_true")
    return parser


def main() -> None:
    """Run the selected command."""

    parser = build_parser()
    args = parser.parse_args()

    if args.command == "send-question":
        require_sender_options(args)
        require_google_options(args)
        state_store = build_bigquery_state_store(
            project_id=args.google_cloud_project,
            dataset=args.bigquery_dataset,
            oauth_client_id=args.oauth_client_id,
            oauth_client_secret=args.oauth_client_secret,
            oauth_refresh_token=args.oauth_refresh_token,
        )
        def generate_question(game_date: date, _state_store: object):
            llm_client = build_openai_llm_client(
                api_key=args.openai_api_key,
                model=args.openai_generator_model,
            )
            llm_generator = LLMQuestionGenerator(
                llm_client=llm_client,
                use_web_search=True,
            )
            topic_discovery_client = build_openai_llm_client(
                api_key=args.openai_api_key,
                model=args.openai_web_search_model,
            )
            return generate_researched_question(
                GenerateResearchedQuestionConfig(game_date=game_date),
                search_client=LLMTopicDiscoverer(llm_client=topic_discovery_client),
                generate_question=llm_generator,
                repair_question=RepairGeneratedQuestion(llm_client=llm_client),
                evaluate_question=LLMQuestionEvaluator(llm_client=llm_client),
            ).candidate.question

        send_result = send_question(
            SendQuestionConfig(
                game_date=args.date,
                sender=args.sender,
                state_store=state_store,
                gmail_user=args.gmail_user,
                oauth_client_id=args.oauth_client_id,
                oauth_client_secret=args.oauth_client_secret,
                oauth_refresh_token=args.oauth_refresh_token,
                google_group_email=args.google_group_email,
                question_generator=generate_question,
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

    elif args.command == "generate-samples":
        if not args.openai_api_key:
            parser.error("generate-samples requires OPENAI_API_KEY or --openai-api-key")
        llm_client = build_openai_llm_client(
            api_key=args.openai_api_key,
            model=args.openai_generator_model,
        )
        candidates = generate_question_samples(
            GenerateQuestionSamplesConfig(
                topic=args.topic,
                sample_count=args.count,
                game_date=args.date,
                category=args.category,
            ),
            generate_question=LLMQuestionGenerator(
                llm_client=llm_client,
                use_web_search=True,
            ),
            repair_question=RepairGeneratedQuestion(llm_client=llm_client),
            evaluate_question=LLMQuestionEvaluator(llm_client=llm_client),
        )
        print(json.dumps({"topic": args.topic, "candidates": [asdict(item) for item in candidates]}, indent=2))

    elif args.command == "score-responses":
        require_sender_options(args)
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
                scoring_date=args.scoring_date,
                game_date=args.game_date,
                sender=args.sender,
                organizer=args.organizer,
                gmail_user=args.gmail_user,
                oauth_client_id=args.oauth_client_id,
                oauth_client_secret=args.oauth_client_secret,
                oauth_refresh_token=args.oauth_refresh_token,
                state_store=state_store,
                answer_interpreter_factory=None
                if args.disable_ai_answer_interpreter
                else lambda question: LLMAnswerInterpreter(
                    llm_client=build_openai_llm_client(
                        api_key=args.openai_api_key,
                        model=args.openai_interpreter_model,
                    ),
                    question=question,
                ),
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

    elif args.command == "adjust-score":
        require_google_options(args)
        state_store = build_bigquery_state_store(
            project_id=args.google_cloud_project,
            dataset=args.bigquery_dataset,
            oauth_client_id=args.oauth_client_id,
            oauth_client_secret=args.oauth_client_secret,
            oauth_refresh_token=args.oauth_refresh_token,
        )

        adjustment_result = apply_score_adjustment(
            ScoreAdjustmentConfig(
                email=args.email,
                game_date=args.game_date,
                series=args.series,
                points_delta=args.points_delta,
                reason=args.reason,
                source_gmail_message_id=args.gmail_message_id,
                idempotency_key=args.idempotency_key,
                state_store=state_store,
                dry_run=args.dry_run,
            )
        )
        status = "Would apply" if args.dry_run and adjustment_result.applied else "Applied"
        if not adjustment_result.applied:
            status = "Skipped duplicate"
        print(
            f"{status} adjustment {adjustment_result.adjustment.idempotency_key}: "
            f"{adjustment_result.monthly_score.email} is now "
            f"{adjustment_result.monthly_score.points} points in {adjustment_result.monthly_score.series}"
        )

    elif args.command == "process-score-adjustments":
        require_sender_options(args)
        require_google_options(args)
        state_store = build_bigquery_state_store(
            project_id=args.google_cloud_project,
            dataset=args.bigquery_dataset,
            oauth_client_id=args.oauth_client_id,
            oauth_client_secret=args.oauth_client_secret,
            oauth_refresh_token=args.oauth_refresh_token,
        )
        organizers = tuple(args.organizer) or (args.sender,)

        processing_result = process_score_adjustment_emails(
            ProcessScoreAdjustmentEmailsConfig(
                sender=args.sender,
                gmail_user=args.gmail_user,
                organizer_emails=organizers,
                oauth_client_id=args.oauth_client_id,
                oauth_client_secret=args.oauth_client_secret,
                oauth_refresh_token=args.oauth_refresh_token,
                state_store=state_store,
                query=args.query,
                max_results=args.max_results,
                dry_run=args.dry_run,
            )
        )
        print(
            f"Processed {len(processing_result.processed)} score adjustment request emails "
            f"for query: {processing_result.searched_query}"
        )
        for adjustment_item in processing_result.processed:
            print(f"- {adjustment_item.message_id}: {adjustment_item.status} ({adjustment_item.response_message_id})")

    elif args.command == "process-correct-answers":
        require_sender_options(args)
        require_google_options(args)
        state_store = build_bigquery_state_store(
            project_id=args.google_cloud_project,
            dataset=args.bigquery_dataset,
            oauth_client_id=args.oauth_client_id,
            oauth_client_secret=args.oauth_client_secret,
            oauth_refresh_token=args.oauth_refresh_token,
        )
        organizers = tuple(args.organizer) or (args.sender,)
        correct_answer_result = process_correct_answer_emails(
            ProcessCorrectAnswerEmailsConfig(
                sender=args.sender,
                gmail_user=args.gmail_user,
                organizer_emails=organizers,
                oauth_client_id=args.oauth_client_id,
                oauth_client_secret=args.oauth_client_secret,
                oauth_refresh_token=args.oauth_refresh_token,
                state_store=state_store,
                query=args.query,
                max_results=args.max_results,
                dry_run=args.dry_run,
            )
        )
        print(
            f"Processed {len(correct_answer_result.processed)} correct-answer request emails "
            f"for query: {correct_answer_result.searched_query}"
        )
        for correct_answer_item in correct_answer_result.processed:
            print(
                f"- {correct_answer_item.message_id}: "
                f"{correct_answer_item.status} ({correct_answer_item.response_message_id})"
            )
