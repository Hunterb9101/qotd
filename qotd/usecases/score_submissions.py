"""Score Player Submissions and report results."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Literal

from pydantic import BaseModel, ConfigDict

from qotd.domain.dates import MOUNTAIN_TIME, answer_cutoff_at, next_scoring_day, previous_game_day, question_subject
from qotd.domain.models import OPTION_LABELS, ReplyCandidate, StoredQuestion
from qotd.domain.canonical import OUTBOUND_PENDING, OutboundMessage, new_id
from qotd.domain.scoring import (
    AnswerInterpretation,
    ScoringResult,
    parse_deterministic_answer,
    parse_iso_datetime,
    score_replies,
)
from qotd.external.email.core import ParsedEmailMessage
from qotd.external.email.gmail import GmailAdapter, search_messages, send_gmail_message
from qotd.external.llm.core import LLMClient
from qotd.external.storage.canonical import CanonicalState
from qotd.presentation.emails import build_organizer_email
from qotd.presentation.organizer_updates import build_organizer_update_body
from qotd.usecases.get_question_history import load_question_for_game_date


MessageFetcher = Callable[[str], list[ParsedEmailMessage]]
AnswerInterpreterFactory = Callable[[StoredQuestion], Callable[[str], AnswerInterpretation]]
DEFAULT_INTERPRET_ANSWER_PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "interpret_answer.md"
REPLY_SUBJECT_PREFIX_RE = re.compile(r"^(?:(?:re|fw|fwd):\s*)+", re.IGNORECASE)


class AnswerInterpretationOutput(BaseModel):
    """Structured answer interpretation returned by an LLM."""

    model_config = ConfigDict(extra="forbid")

    option: Literal["A", "B", "C", "D", "UNKNOWN"]
    needs_review: bool


@dataclass(frozen=True)
class LLMAnswerInterpreter:
    """Interpret freeform QOTD replies using a provider-neutral LLM client."""

    llm_client: LLMClient
    question: StoredQuestion
    prompt_path: Path = DEFAULT_INTERPRET_ANSWER_PROMPT_PATH
    max_output_tokens: int = 200

    def __call__(self, body_text: str) -> AnswerInterpretation:
        """Interpret one Player Submission as A/B/C/D/UNKNOWN."""

        payload = {
            "question": {
                "prompt": self.question.prompt,
                "options": {label: self.question.options[label] for label in OPTION_LABELS},
            },
            "reply_text": body_text,
        }
        data = self.llm_client.create_structured_response(
            prompt_path=self.prompt_path,
            payload=payload,
            response_model=AnswerInterpretationOutput,
            schema_name="qotd_answer_interpretation",
            max_output_tokens=self.max_output_tokens,
        )
        needs_review = data.needs_review or data.option == "UNKNOWN"
        return AnswerInterpretation(option=data.option, needs_review=needs_review)


@dataclass(frozen=True)
class ScoreResponsesConfig:
    """Runtime config for the morning response scoring workflow."""

    scoring_date: date | None
    sender: str
    organizer: str
    gmail_user: str
    oauth_client_id: str
    oauth_client_secret: str
    oauth_refresh_token: str
    state_store: object
    game_date: date | None = None
    answer_interpreter_factory: AnswerInterpreterFactory | None = None
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
    skipped_reason: str | None = None


def today_mountain() -> date:
    """Return today's date in Mountain time."""

    return datetime.now(MOUNTAIN_TIME).date()


def gmail_reply_query(*, game_date: date, scoring_date: date) -> str:
    """Build a dated Gmail search query for QOTD replies."""

    # Gmail date search is day-granular; exact send/cutoff times are filtered in code.
    after = game_date.strftime("%Y/%m/%d")
    before = (scoring_date + timedelta(days=1)).strftime("%Y/%m/%d")
    return f'subject:"{question_subject(game_date)}" after:{after} before:{before}'


def is_question_reply_subject(subject: str, *, game_date: str) -> bool:
    """Return whether a reply subject belongs to the dated QOTD question."""

    normalized = REPLY_SUBJECT_PREFIX_RE.sub("", subject.strip())
    return normalized == question_subject(game_date)


def collect_reply_candidates(
    messages: list[ParsedEmailMessage],
    *,
    question: StoredQuestion,
    sender: str,
) -> list[ReplyCandidate]:
    """Convert parsed messages into reply candidates for a question."""

    question_sent_at = parse_iso_datetime(question.created_at)
    candidates: list[ReplyCandidate] = []
    for parsed in messages:
        if parsed.sender_email == sender.lower():
            continue
        if not is_question_reply_subject(parsed.subject, game_date=question.game_date):
            continue
        if parsed.sent_at is not None and parsed.sent_at.replace(tzinfo=parsed.sent_at.tzinfo or UTC) <= question_sent_at:
            continue
        try:
            candidates.append(GmailAdapter.build_reply_candidate(parsed, game_date=question.game_date))
        except ValueError:
            continue
    return candidates


def score_responses(
    config: ScoreResponsesConfig,
    *,
    fetch_messages: MessageFetcher | None = None,
) -> ScoreResponsesResult:
    """Collect, score, persist, and send the organizer scoring update."""

    if config.game_date is None:
        scoring_date = config.scoring_date or today_mountain()
        game_date = previous_game_day(scoring_date)
    else:
        game_date = config.game_date
        scoring_date = config.scoring_date or next_scoring_day(game_date)

    question = (
        load_question_for_game_date(config.state_store, game_date)
        if isinstance(config.state_store, CanonicalState)
        else _load_legacy_question_for_game_date(config.state_store, game_date)
    )
    query = gmail_reply_query(game_date=game_date, scoring_date=scoring_date)
    if not question.correct_option:
        action = "set-answer" if isinstance(config.state_store, CanonicalState) else "set-correct-answer"
        body = (
            f"QOTD scoring skipped for {question.game_date}.\n\n"
            "The Game does not have an Answer yet. "
            "Send an Answer instruction before rerunning scoring.\n\n"
            "Expected template:\n"
            f"Action: {action}\n"
            f"Day: {question.game_date}\n"
            "Correct option: C\n"
            "Source URL: https://example.com/source-for-answer\n"
        )
        if isinstance(config.state_store, CanonicalState):
            game = config.state_store.find_game(day=game_date)
            if game is None:
                raise RuntimeError(f"No Game found for {game_date.isoformat()}")
            intent = config.state_store.record_outbound_message(
                OutboundMessage(
                    id=new_id(),
                    idempotency_key=f"missing-answer:{game.id}",
                    message_type="organizer_scoring_update",
                    recipient=config.organizer,
                    subject=f"QOTD scoring skipped - {game_date.isoformat()}",
                    body_text=body,
                    status=OUTBOUND_PENDING,
                    created_at=datetime.now(UTC),
                    game_id=game.id,
                )
            )
            organizer_message_id = intent.id
        elif config.dry_run:
            organizer_message_id = f"dry-run:{game_date.isoformat()}"
        else:
            organizer_message = build_organizer_email(
                sender=config.sender,
                organizer=config.organizer,
                subject=f"QOTD scoring skipped - {game_date.isoformat()}",
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
            scoring=ScoringResult(
                game_date=question.game_date,
                correct=(),
                incorrect=(),
                needs_review=(),
                skipped_processing_keys=(),
                standings=(),
            ),
            reply_count=0,
            organizer_update_body=body,
            organizer_message_id=organizer_message_id,
            gmail_query=query,
            skipped_reason="missing_correct_answer",
        )
    if fetch_messages is None:
        def fetch_messages(gmail_query: str) -> list[ParsedEmailMessage]:
            return search_messages(
                user_id=config.gmail_user,
                oauth_client_id=config.oauth_client_id,
                oauth_client_secret=config.oauth_client_secret,
                oauth_refresh_token=config.oauth_refresh_token,
                query=gmail_query,
            )

    replies = collect_reply_candidates(fetch_messages(query), question=question, sender=config.sender)
    interpret_answer = None
    if config.answer_interpreter_factory is not None:
        ai_interpret_answer = config.answer_interpreter_factory(question)

        def interpret_answer(body_text: str) -> AnswerInterpretation:
            deterministic = parse_deterministic_answer(body_text)
            if not deterministic.needs_review:
                return deterministic
            return ai_interpret_answer(body_text)

    scoring_interpreter = parse_deterministic_answer if interpret_answer is None else interpret_answer
    if isinstance(config.state_store, CanonicalState):
        game = config.state_store.find_game(day=game_date)
        if game is None:
            raise RuntimeError(f"No Game found for {game_date.isoformat()}")
        config.state_store.score_game(replace(game, scored_at=datetime.now(UTC)))
        scoring = ScoringResult(
            game_date=question.game_date,
            correct=(),
            incorrect=(),
            needs_review=(),
            skipped_processing_keys=(),
            standings=(),
        )
        body = build_organizer_update_body(question, scoring)
        return ScoreResponsesResult(
            question=question,
            scoring=scoring,
            reply_count=0,
            organizer_update_body=body,
            organizer_message_id=f"canonical:{game.id}",
            gmail_query=query,
        )
    legacy_state: Any = config.state_store
    scoring = score_replies(
        question=question,
        replies=replies,
        cutoff_at=answer_cutoff_at(scoring_date),
        processed_at=datetime.now(UTC),
        existing_reply_processing_records=legacy_state.read_reply_processing_records(game_date=question.game_date),
        existing_monthly_score_records=legacy_state.read_monthly_scores(),
        interpret_answer=scoring_interpreter,
    )
    for score_record in scoring.monthly_score_updates:
        legacy_state.append_monthly_score(score_record)
    for processing_update in scoring.reply_processing_updates:
        legacy_state.append_reply_processing_record(
            processing_update.record,
            interpreted_option=processing_update.interpreted_option,
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


def _load_legacy_question_for_game_date(state_store: object, game_date: date) -> StoredQuestion:
    """Load the temporary snapshot Question until Phase 4 migrates scoring."""

    state: Any = state_store
    game_date_text = game_date.isoformat()
    matches = [
        StoredQuestion.from_record(record)
        for record in state.read_question_records()
        if record.get("game_date") == game_date_text
    ]
    if not matches:
        raise RuntimeError(f"No stored QOTD question found for {game_date_text}")
    question = matches[-1]
    updates = state.read_correct_answer_updates(game_date=game_date_text)
    if not updates:
        return question
    latest = updates[-1]
    return replace(question, correct_option=str(latest["correct_option"]), source_url=str(latest["source_url"]))
