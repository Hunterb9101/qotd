"""Manual score adjustment workflow."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from email.message import EmailMessage
from typing import Callable

from qotd.domain.contacts import normalize_email_addresses
from qotd.domain.dates import monthly_series
from qotd.domain.models import ManualAdjustment, MonthlyScore
from qotd.domain.scoring import latest_score_map, standings_from_scores
from qotd.external.email.core import ParsedEmailMessage
from qotd.external.email.gmail import mark_gmail_message_read, search_messages, send_gmail_message
from qotd.external.storage.core import StorageClient
from qotd.presentation.emails import build_organizer_email


@dataclass(frozen=True)
class ScoreAdjustmentConfig:
    """Configuration for applying one manual score adjustment."""

    email: str
    points_delta: int
    reason: str
    state_store: StorageClient
    game_date: date | None = None
    series: str | None = None
    source_gmail_message_id: str = ""
    idempotency_key: str | None = None
    dry_run: bool = False


@dataclass(frozen=True)
class ScoreAdjustmentResult:
    """Result of a manual score adjustment attempt."""

    adjustment: ManualAdjustment
    monthly_score: MonthlyScore
    standings: tuple[MonthlyScore, ...]
    applied: bool


@dataclass(frozen=True)
class ParsedScoreAdjustmentRequest:
    """Structured score adjustment data parsed from an organizer email."""

    participant_email: str
    points_delta: int
    reason: str
    game_date: date | None = None
    series: str | None = None
    source_gmail_message_id: str = ""
    idempotency_key: str | None = None


@dataclass(frozen=True)
class ProcessScoreAdjustmentEmailsConfig:
    """Configuration for processing score adjustment request emails."""

    sender: str
    gmail_user: str
    organizer_emails: tuple[str, ...]
    oauth_client_id: str
    oauth_client_secret: str
    oauth_refresh_token: str
    state_store: StorageClient
    query: str = 'is:unread "Action: adjust-score"'
    max_results: int = 25
    dry_run: bool = False


@dataclass(frozen=True)
class ScoreAdjustmentEmailProcessingResult:
    """Result for one score adjustment request email."""

    message_id: str
    sender_email: str
    accepted: bool
    response_message_id: str
    status: str
    adjustment_result: ScoreAdjustmentResult | None = None


@dataclass(frozen=True)
class ProcessScoreAdjustmentEmailsResult:
    """Summary of one management-email processing run."""

    searched_query: str
    processed: tuple[ScoreAdjustmentEmailProcessingResult, ...]


def adjustment_series(*, game_date: date | None, series: str | None) -> str:
    """Resolve the monthly score series for an adjustment."""

    if game_date is None and series is None:
        raise ValueError("either game_date or series is required")
    if game_date is not None and series is not None:
        raise ValueError("provide only one of game_date or series")
    if series is not None:
        if len(series) != 4 or not series.isdigit():
            raise ValueError("series must use MMYY format")
        return series
    assert game_date is not None
    return monthly_series(game_date)


def build_adjustment_idempotency_key(
    *,
    email: str,
    reason: str,
    game_date: date | None,
    series: str,
) -> str:
    """Build the default idempotency key for a manual adjustment."""

    period = game_date.isoformat() if game_date is not None else series
    return f"manual:{period}:{email}:{reason}"


def question_exists(records: list[dict[str, object]], *, game_date: date) -> bool:
    """Return whether a stored question exists for a game date."""

    expected = game_date.isoformat()
    return any(record.get("game_date") == expected for record in records)


def parse_score_adjustment_email(body_text: str) -> ParsedScoreAdjustmentRequest:
    """Parse a plain-text score adjustment request email."""

    fields: dict[str, str] = {}
    for raw_line in body_text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if ":" not in raw_line:
            continue
        key, value = raw_line.split(":", 1)
        normalized_key = key.strip().lower()
        if normalized_key:
            fields[normalized_key] = value.strip()

    action = fields.get("action", "")
    if action.casefold() != "adjust-score":
        raise ValueError("Action must be adjust-score")

    participant = fields.get("participant", "")
    points_text = fields.get("points", "")
    reason = fields.get("reason", "")
    if not participant:
        raise ValueError("Participant is required")
    if not points_text:
        raise ValueError("Points is required")
    if not reason:
        raise ValueError("Reason is required")

    try:
        points_delta = int(points_text)
    except ValueError as error:
        raise ValueError("Points must be an integer") from error

    game_date_text = fields.get("game date", "")
    month_text = fields.get("month", "")
    series_text = fields.get("series", "")
    if game_date_text and (month_text or series_text):
        raise ValueError("Use either Game date or Month, not both")
    if month_text and series_text:
        raise ValueError("Use either Month or Series, not both")
    if not game_date_text and not month_text and not series_text:
        raise ValueError("Game date or Month is required")

    game_date = date.fromisoformat(game_date_text) if game_date_text else None
    series = None
    if month_text:
        series = parse_month_series(month_text)
    elif series_text:
        series = series_text

    return ParsedScoreAdjustmentRequest(
        participant_email=participant,
        points_delta=points_delta,
        reason=reason,
        game_date=game_date,
        series=series,
        source_gmail_message_id=fields.get("gmail message id", ""),
        idempotency_key=fields.get("idempotency key") or None,
    )


def parse_month_series(value: str) -> str:
    """Parse MMYY or YYYY-MM month text into an MMYY score series."""

    stripped = value.strip()
    if len(stripped) == 4 and stripped.isdigit():
        return stripped
    month_date = date.fromisoformat(f"{stripped}-01")
    return monthly_series(month_date)


def apply_score_adjustment(config: ScoreAdjustmentConfig) -> ScoreAdjustmentResult:
    """Apply one manual score adjustment and return updated standings."""

    normalized_emails = normalize_email_addresses([config.email])
    if not normalized_emails:
        raise ValueError("email is required")
    email = normalized_emails[0]
    reason = config.reason.strip()
    if not reason:
        raise ValueError("reason is required")
    if config.points_delta == 0:
        raise ValueError("points_delta cannot be 0")

    series = adjustment_series(game_date=config.game_date, series=config.series)
    if config.game_date is not None and not question_exists(
        config.state_store.read_question_records(),
        game_date=config.game_date,
    ):
        raise ValueError(f"no stored question exists for {config.game_date.isoformat()}")

    idempotency_key = config.idempotency_key or build_adjustment_idempotency_key(
        email=email,
        reason=reason,
        game_date=config.game_date,
        series=series,
    )

    existing_adjustments = config.state_store.read_manual_adjustments()
    existing_scores = config.state_store.read_monthly_scores(series=series)
    scores = latest_score_map(existing_scores, series=series)
    current_points = scores.get(email, 0)
    updated_points = current_points + config.points_delta

    adjustment = ManualAdjustment(
        series=series,
        email=email,
        points_delta=config.points_delta,
        source_gmail_message_id=config.source_gmail_message_id,
        idempotency_key=idempotency_key,
        reason=reason,
        created_at=datetime.now(UTC).isoformat(),
    )
    monthly_score = MonthlyScore(series=series, email=email, points=updated_points)

    if any(record.get("idempotency_key") == idempotency_key for record in existing_adjustments):
        return ScoreAdjustmentResult(
            adjustment=adjustment,
            monthly_score=MonthlyScore(series=series, email=email, points=current_points),
            standings=standings_from_scores(series, scores),
            applied=False,
        )

    scores[email] = updated_points
    if not config.dry_run:
        config.state_store.append_manual_adjustment(adjustment)
        config.state_store.append_monthly_score(monthly_score)

    return ScoreAdjustmentResult(
        adjustment=adjustment,
        monthly_score=monthly_score,
        standings=standings_from_scores(series, scores),
        applied=True,
    )


def build_score_adjustment_response_body(
    *,
    request_message: ParsedEmailMessage,
    result: ScoreAdjustmentResult | None,
    error: str | None = None,
) -> str:
    """Build the organizer response body for an adjustment request."""

    if error is not None:
        return (
            "Score adjustment request rejected.\n\n"
            f"Message: {request_message.message_id}\n"
            f"Reason: {error}\n\n"
            "Expected template:\n"
            "Action: adjust-score\n"
            "Participant: person@example.com\n"
            "Game date: 2026-07-08\n"
            "Points: 1\n"
            "Reason: unclear_answer_accepted\n"
            "Gmail message ID: msg_123\n"
        )

    if result is None:
        raise ValueError("result is required when error is not provided")
    status = "Skipped duplicate" if not result.applied else "Applied"
    standings = "\n".join(f"- {score.email}: {score.points}" for score in result.standings)
    return (
        f"{status} score adjustment.\n\n"
        f"Participant: {result.monthly_score.email}\n"
        f"Series: {result.monthly_score.series}\n"
        f"Points delta: {result.adjustment.points_delta}\n"
        f"Reason: {result.adjustment.reason}\n"
        f"Idempotency key: {result.adjustment.idempotency_key}\n"
        f"Updated points: {result.monthly_score.points}\n\n"
        "Current standings:\n"
        f"{standings or '(none)'}\n"
    )


def process_score_adjustment_emails(
    config: ProcessScoreAdjustmentEmailsConfig,
    *,
    fetch_messages: Callable[[str], list[ParsedEmailMessage]] | None = None,
    send_message: Callable[[EmailMessage], str] | None = None,
    mark_message_handled: Callable[[str], None] | None = None,
) -> ProcessScoreAdjustmentEmailsResult:
    """Process structured score adjustment emails from approved organizers."""

    approved_senders = set(normalize_email_addresses(config.organizer_emails))
    if not approved_senders:
        raise ValueError("at least one organizer email is required")

    fetch = fetch_messages or (
        lambda query: search_messages(
            user_id=config.gmail_user,
            oauth_client_id=config.oauth_client_id,
            oauth_client_secret=config.oauth_client_secret,
            oauth_refresh_token=config.oauth_refresh_token,
            query=query,
            max_results=config.max_results,
        )
    )
    send = send_message or (
        lambda message: send_gmail_message(
            message,
            user_id=config.gmail_user,
            oauth_client_id=config.oauth_client_id,
            oauth_client_secret=config.oauth_client_secret,
            oauth_refresh_token=config.oauth_refresh_token,
        )
    )
    mark_handled = mark_message_handled or (
        lambda message_id: mark_gmail_message_read(
            message_id,
            user_id=config.gmail_user,
            oauth_client_id=config.oauth_client_id,
            oauth_client_secret=config.oauth_client_secret,
            oauth_refresh_token=config.oauth_refresh_token,
        )
    )

    processed: list[ScoreAdjustmentEmailProcessingResult] = []
    for message in fetch(config.query):
        normalized_sender = normalize_email_addresses([message.sender_email])
        sender_email = normalized_sender[0] if normalized_sender else message.sender_email
        adjustment_result: ScoreAdjustmentResult | None = None
        error: str | None = None

        if sender_email not in approved_senders:
            error = f"sender is not approved: {sender_email}"
        else:
            try:
                request = parse_score_adjustment_email(message.body_text)
                adjustment_result = apply_score_adjustment(
                    ScoreAdjustmentConfig(
                        email=request.participant_email,
                        points_delta=request.points_delta,
                        reason=request.reason,
                        state_store=config.state_store,
                        game_date=request.game_date,
                        series=request.series,
                        source_gmail_message_id=request.source_gmail_message_id or message.message_id,
                        idempotency_key=request.idempotency_key,
                        dry_run=config.dry_run,
                    )
                )
            except ValueError as exc:
                error = str(exc)

        response_body = build_score_adjustment_response_body(
            request_message=message,
            result=adjustment_result,
            error=error,
        )
        response = build_organizer_email(
            sender=config.sender,
            organizer=sender_email,
            subject="QOTD score adjustment result",
            body=response_body,
        )
        response_message_id = f"dry-run:{message.message_id}"
        if not config.dry_run:
            response_message_id = send(response)
            mark_handled(message.message_id)

        processed.append(
            ScoreAdjustmentEmailProcessingResult(
                message_id=message.message_id,
                sender_email=sender_email,
                accepted=error is None,
                response_message_id=response_message_id,
                status=error or ("skipped_duplicate" if adjustment_result and not adjustment_result.applied else "applied"),
                adjustment_result=adjustment_result,
            )
        )

    return ProcessScoreAdjustmentEmailsResult(
        searched_query=config.query,
        processed=tuple(processed),
    )
