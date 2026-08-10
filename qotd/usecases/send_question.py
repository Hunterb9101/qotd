"""Noon question generation and send workflow."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime
from email.message import EmailMessage
from typing import Callable

from qotd.domain.dates import question_subject
from qotd.domain.generator import generate_placeholder_question
from qotd.domain.canonical import Game, OUTBOUND_PENDING, OutboundMessage, new_id
from qotd.domain.models import Question, StoredQuestion
from qotd.domain.validation import validate_question
from qotd.external.email.core import ParsedEmailMessage
from qotd.external.email.runtime import build_player_email, search_messages, send_gmail_message
from qotd.external.storage.canonical import CanonicalState
from qotd.usecases.check_manual_question import MessageFetcher, check_manual_question
from qotd.usecases.publish_game import publish_automated_game
from qotd.usecases.get_question_history import find_latest_scored_question_before, stored_question_from_game
from qotd.usecases.get_score_history import PlayerResults, load_player_results
from qotd.usecases.deliver_outbound_message import deliver_outbound_message


QuestionGeneratorForDate = Callable[[date, object], Question]
MessageSender = Callable[[EmailMessage], str]
LOGGER = logging.getLogger(__name__)
QUESTION_ALREADY_EXISTS = "question_subject_already_exists"


@dataclass(frozen=True)
class SendQuestionConfig:
    """Runtime config for the phase 1 send workflow."""

    game_date: date
    sender: str
    gmail_user: str
    oauth_client_id: str
    oauth_client_secret: str
    oauth_refresh_token: str
    state_store: object
    google_group_email: str = ""
    question_generator: QuestionGeneratorForDate | None = None
    dry_run: bool = False


@dataclass(frozen=True)
class SendQuestionResult:
    """Result of the phase 1 send workflow."""

    record: StoredQuestion
    email_body: str
    recipient_count: int
    skipped_generated_send: bool = False
    outcome: str = "sent"
    reason: str | None = None
    subject: str | None = None
    matched_gmail_message_id: str | None = None


def send_question(
    config: SendQuestionConfig,
    *,
    fetch_messages: MessageFetcher | None = None,
    send_message: MessageSender | None = None,
) -> SendQuestionResult:
    """Generate, send, and persist a QOTD question."""

    if not isinstance(config.state_store, CanonicalState):
        raise TypeError("canonical Game state is required")
    state = config.state_store
    publication_key = f"publication:{config.game_date.isoformat()}"

    if fetch_messages is None and not config.dry_run:
        def fetch_messages(gmail_query: str) -> list[ParsedEmailMessage]:
            return search_messages(
                user_id=config.gmail_user,
                oauth_client_id=config.oauth_client_id,
                oauth_client_secret=config.oauth_client_secret,
                oauth_refresh_token=config.oauth_refresh_token,
                query=gmail_query,
            )

    existing_intent = state.find_outbound_message(idempotency_key=publication_key)
    if existing_intent is not None:
        existing_game = state.find_game(day=config.game_date)
        if existing_game is None:
            raise RuntimeError("Question publication intent has no Game")
        if existing_intent.status == OUTBOUND_PENDING:
            if fetch_messages is None:
                raise RuntimeError("Pending Question publication requires Gmail reconciliation before retry")
            deliver_outbound_message(
                state=state, intent=existing_intent, sender=config.sender, fetch_messages=fetch_messages,
                send_message=_gmail_sender(config), is_new=False,
            )
        return _published_question_result(existing_game)

    if fetch_messages is not None:
        manual_question = check_manual_question(
            game_date=config.game_date,
            sender=config.sender,
            state=state,
            fetch_messages=fetch_messages,
        )
        if manual_question is not None:
            subject = question_subject(config.game_date)
            record = (
                stored_question_from_game(manual_question)
                if isinstance(manual_question, Game)
                else manual_question
            )
            LOGGER.info(
                "job=send_question game_date=%s outcome=skipped "
                "reason=%s subject=%r gmail_message_id=%s",
                config.game_date.isoformat(),
                QUESTION_ALREADY_EXISTS,
                subject,
                record.gmail_message_id,
            )
            return SendQuestionResult(
                record=record,
                email_body=record.prompt,
                recipient_count=0,
                skipped_generated_send=True,
                outcome="skipped",
                reason=QUESTION_ALREADY_EXISTS,
                subject=subject,
                matched_gmail_message_id=record.gmail_message_id,
            )

    google_group_email = config.google_group_email.strip().lower()
    if not config.dry_run and not google_group_email:
        raise RuntimeError("Google Group email is required for Player delivery")

    if config.question_generator is None:
        question = generate_placeholder_question(config.game_date.isoformat())
    else:
        question = config.question_generator(config.game_date, config.state_store)
    validate_question(question)
    previous_question = find_latest_scored_question_before(state, config.game_date)
    player_results = (
        load_player_results(state, date.fromisoformat(previous_question.game_date))
        if previous_question is not None
        else PlayerResults(point_earners=(), standings=())
    )
    email_message = build_player_email(
        question,
        config.sender,
        delivery_address=google_group_email or None,
        point_earners=player_results.point_earners,
        previous_question=previous_question,
        standings=player_results.standings,
    )

    published_at = datetime.now(UTC)
    existing_game = state.find_game(day=config.game_date)
    game_id = existing_game.id if existing_game is not None else new_id()
    outbound_message = OutboundMessage(
        id=new_id(),
        idempotency_key=publication_key,
        message_type="question_publication",
        recipient=google_group_email,
        subject=question_subject(config.game_date),
        body_text=email_message.get_content(),
        status=OUTBOUND_PENDING,
        created_at=published_at,
        game_id=game_id,
    )
    record = stored_question_from_game(
        publish_automated_game(
            state=state,
            game_day=config.game_date,
            question=question,
            message_id=outbound_message.idempotency_key,
            published_at=published_at,
            outbound_message=outbound_message,
            game_id=game_id,
        )
    )
    if not config.dry_run:
        assert fetch_messages is not None
        deliver_outbound_message(
            state=state, intent=outbound_message, sender=config.sender, fetch_messages=fetch_messages,
            send_message=send_message or _gmail_sender(config), is_new=True,
        )
    return SendQuestionResult(
        record=record,
        email_body=email_message.get_content(),
        recipient_count=1,
        subject=question_subject(config.game_date),
    )


def _published_question_result(game: Game) -> SendQuestionResult:
    record = stored_question_from_game(game)
    return SendQuestionResult(
        record=record,
        email_body=game.question_prompt or "",
        recipient_count=1,
        skipped_generated_send=True,
        outcome="skipped",
        reason="publication_intent_already_exists",
        subject=game.publication_subject,
    )


def _gmail_sender(config: SendQuestionConfig) -> MessageSender:
    return lambda message: send_gmail_message(
        message,
        user_id=config.gmail_user,
        oauth_client_id=config.oauth_client_id,
        oauth_client_secret=config.oauth_client_secret,
        oauth_refresh_token=config.oauth_refresh_token,
    )
