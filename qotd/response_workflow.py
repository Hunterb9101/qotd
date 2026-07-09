"""Morning response collection and scoring workflow."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, Callable

from qotd.dates import MOUNTAIN_TIME, answer_cutoff_at, previous_game_day
from qotd.email_parsing import ReplyCandidate, build_reply_candidate, parse_gmail_message
from qotd.emailing import build_organizer_email, send_gmail_message
from qotd.gmail import search_messages
from qotd.models import StoredQuestion
from qotd.scoring import ScoringResult, build_organizer_update_body, parse_iso_datetime, score_replies
from qotd.storage import StateStore


MessageFetcher = Callable[[str], list[dict[str, Any]]]


@dataclass(frozen=True)
class ScoreResponsesConfig:
    """Runtime config for the morning response scoring workflow."""

    scoring_date: date
    sender: str
    organizer: str
    gmail_user: str
    oauth_client_id: str
    oauth_client_secret: str
    oauth_refresh_token: str
    state_store: StateStore
    dry_run: bool = False


@dataclass(frozen=True)
class ScoreResponsesResult:
    """Result of the response scoring workflow."""

    question: StoredQuestion
    scoring: ScoringResult
    reply_count: int
    organizer_update_body: str
    organizer_message_id: str
    gmail_query: str


def today_mountain() -> date:
    """Return today's date in Mountain time."""

    return datetime.now(MOUNTAIN_TIME).date()


def question_from_record(record: dict[str, Any]) -> StoredQuestion:
    """Build a stored question from a JSON record."""

    return StoredQuestion(
        game_date=str(record["game_date"]),
        prompt=str(record["prompt"]),
        options=dict(record["options"]),
        correct_option=str(record["correct_option"]),
        source_note=str(record["source_note"]),
        source_url=str(record["source_url"]),
        source=str(record["source"]),
        gmail_message_id=str(record["gmail_message_id"]),
        created_at=str(record["created_at"]),
    )


def load_question_for_game_date(state_store: StateStore, game_date: date) -> StoredQuestion:
    """Load the latest stored question for a game date."""

    game_date_text = game_date.isoformat()
    matches = [
        question_from_record(record)
        for record in state_store.read_question_records()
        if record.get("game_date") == game_date_text
    ]
    if not matches:
        raise RuntimeError(f"No stored QOTD question found for {game_date_text}")
    return matches[-1]


def gmail_reply_query(*, game_date: date, scoring_date: date) -> str:
    """Build a broad Gmail search query for QOTD replies."""

    # Gmail date search is day-granular; exact send/cutoff times are filtered in code.
    after = game_date.strftime("%Y/%m/%d")
    before = (scoring_date + timedelta(days=1)).strftime("%Y/%m/%d")
    return f"subject:QOTD after:{after} before:{before}"


def collect_reply_candidates(
    messages: list[dict[str, Any]],
    *,
    question: StoredQuestion,
    sender: str,
) -> list[ReplyCandidate]:
    """Parse Gmail messages into reply candidates for a question."""

    question_sent_at = parse_iso_datetime(question.created_at)
    candidates: list[ReplyCandidate] = []
    for message in messages:
        parsed = parse_gmail_message(message)
        if parsed.sender_email == sender.lower():
            continue
        if parsed.sent_at is not None and parsed.sent_at.replace(tzinfo=parsed.sent_at.tzinfo or UTC) <= question_sent_at:
            continue
        try:
            candidates.append(build_reply_candidate(parsed, game_date=question.game_date))
        except ValueError:
            continue
    return candidates


def score_responses(
    config: ScoreResponsesConfig,
    *,
    fetch_messages: MessageFetcher | None = None,
) -> ScoreResponsesResult:
    """Collect, score, persist, and send the organizer scoring update."""

    game_date = previous_game_day(config.scoring_date)
    question = load_question_for_game_date(config.state_store, game_date)
    query = gmail_reply_query(game_date=game_date, scoring_date=config.scoring_date)
    if fetch_messages is None:
        def fetch_messages(gmail_query: str) -> list[dict[str, Any]]:
            return search_messages(
                user_id=config.gmail_user,
                oauth_client_id=config.oauth_client_id,
                oauth_client_secret=config.oauth_client_secret,
                oauth_refresh_token=config.oauth_refresh_token,
                query=gmail_query,
            )

    replies = collect_reply_candidates(fetch_messages(query), question=question, sender=config.sender)
    scoring = score_replies(
        question=question,
        replies=replies,
        cutoff_at=answer_cutoff_at(config.scoring_date),
        processed_at=datetime.now(UTC),
        state_store=config.state_store,
    )
    body = build_organizer_update_body(question, scoring)
    if config.dry_run:
        organizer_message_id = f"dry-run:{game_date.isoformat()}"
    else:
        organizer_message = build_organizer_email(
            sender=config.sender,
            organizer=config.organizer,
            subject=f"QOTD scoring update - {game_date.isoformat()}",
            body=body,
        )
        organizer_message_id = send_gmail_message(
            organizer_message,
            user_id=config.gmail_user,
            oauth_client_id=config.oauth_client_id,
            oauth_client_secret=config.oauth_client_secret,
            oauth_refresh_token=config.oauth_refresh_token,
        )

    return ScoreResponsesResult(
        question=question,
        scoring=scoring,
        reply_count=len(replies),
        organizer_update_body=body,
        organizer_message_id=organizer_message_id,
        gmail_query=query,
    )
