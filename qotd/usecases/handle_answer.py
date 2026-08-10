"""Handle canonical Organizer Instructions that set Game Answers."""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, datetime
from urllib.parse import urlparse

from qotd.domain.canonical import (
    GAME_PENDING,
    INSTRUCTION_APPLIED,
    INSTRUCTION_REJECTED,
    OUTBOUND_PENDING,
    Game,
    OrganizerInstruction,
    OutboundMessage,
    Series,
    gmail_message_key,
    new_id,
)
from qotd.domain.dates import answer_cutoff_at, next_scoring_day
from qotd.domain.models import OPTION_LABELS
from qotd.external.email.core import ParsedEmailMessage
from qotd.external.storage.canonical import CanonicalState
from qotd.usecases.parse_organizer_instruction import OrganizerInstructionPayload, parse_organizer_instruction_payload


ANSWER_TEMPLATE_SOURCE_URL = "https://example.com/source-for-answer"


@dataclass(frozen=True)
class AnswerInstructionResult:
    """The Organizer Instruction and Game produced by an Answer request."""

    instruction: OrganizerInstruction
    game: Game | None
    outbound_message: OutboundMessage | None = None


def apply_answer_instruction(
    *,
    state: CanonicalState,
    message: ParsedEmailMessage,
    processed_at: datetime,
    outcome_recipient: str | None = None,
) -> AnswerInstructionResult:
    """Apply one canonical `set-answer` Organizer Instruction idempotently."""

    try:
        payload = parse_organizer_instruction_payload(message.body_text)
        if payload.action != "set-answer":
            raise ValueError("Organizer Instruction Action must be set-answer")
        return _apply_validated_answer_instruction(
            state=state, message=message, processed_at=processed_at, payload=payload, outcome_recipient=outcome_recipient
        )
    except ValueError as exc:
        instruction = _new_instruction(
            message=message, processed_at=processed_at, action=_action_from_message(message.body_text),
            status=INSTRUCTION_REJECTED, rejection_reason=str(exc),
        )
        outbound = _outcome_message(
            instruction=instruction, message=message, recipient=outcome_recipient, processed_at=processed_at,
            body=_rejection_body(message=message, reason=str(exc)),
        )
        if outbound is not None:
            instruction = state.record_organizer_instruction_outcome(
                instruction=instruction, outbound_message=outbound
            )
            outbound = state.find_outbound_message(idempotency_key=outbound.idempotency_key)
        else:
            instruction = state.record_organizer_instruction(instruction)
        return AnswerInstructionResult(
            instruction=instruction,
            game=None,
            outbound_message=outbound,
        )


def _apply_validated_answer_instruction(
    *, state: CanonicalState, message: ParsedEmailMessage, processed_at: datetime,
    payload: OrganizerInstructionPayload, outcome_recipient: str | None,
) -> AnswerInstructionResult:
    """Validate and apply a parsed Answer instruction."""

    fields = payload.fields
    try:
        game_day = date.fromisoformat(fields["day"])
        correct_option = fields["correct option"].upper()
        source_url = fields["source url"]
    except KeyError as exc:
        raise ValueError(f"Organizer Instruction requires {exc.args[0].title()}") from exc
    if correct_option not in OPTION_LABELS:
        raise ValueError("Correct option must be one of A, B, C, or D")
    existing_game = state.find_game(day=game_day)
    if existing_game is not None and existing_game.correct_option is not None:
        if existing_game.correct_option != correct_option:
            raise ValueError("Game Answer conflicts with the existing Answer")
    if existing_game is not None and existing_game.question_options is not None:
        if correct_option not in existing_game.question_options:
            raise ValueError("Correct option is not present in the Game Question")
    parsed_url = urlparse(source_url)
    if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
        raise ValueError("Source URL must be a valid http or https URL")
    if source_url == ANSWER_TEMPLATE_SOURCE_URL:
        raise ValueError("Source URL must replace the Answer instruction template value")

    days_in_month = calendar.monthrange(game_day.year, game_day.month)[1]
    series = Series(
        id=new_id(),
        name=game_day.strftime("%Y-%m"),
        starts_on=game_day.replace(day=1),
        ends_on=game_day.replace(day=days_in_month),
        created_at=processed_at,
        updated_at=processed_at,
    )
    instruction = OrganizerInstruction(
        id=new_id(),
        source_message_key=gmail_message_key(message.message_id),
        sender_email=message.sender_email.strip().lower(),
        subject=message.subject,
        received_at=message.sent_at or processed_at,
        action=payload.action,
        status=INSTRUCTION_APPLIED,
        processed_at=processed_at,
    )
    game = Game(
        id=new_id(),
        series_id=series.id,
        day=game_day,
        status=GAME_PENDING,
        publication_mode="manual",
        deadline_at=answer_cutoff_at(next_scoring_day(game_day)),
        correct_option=correct_option,
        answer_source_url=source_url,
        answer_source_note=fields.get("source note"),
        answer_instruction_id=instruction.id,
        created_at=processed_at,
        updated_at=processed_at,
    )
    outbound = _outcome_message(
        instruction=instruction, message=message, recipient=outcome_recipient, processed_at=processed_at,
        body=_applied_body(game_day=game_day, correct_option=correct_option, source_url=source_url),
    )
    instruction, game = state.record_answer_instruction(
        instruction=instruction,
        series=series,
        game=game,
        outbound_message=outbound,
    )
    if outbound is not None:
        outbound = state.find_outbound_message(idempotency_key=outbound.idempotency_key)
    return AnswerInstructionResult(instruction=instruction, game=game, outbound_message=outbound)


def _new_instruction(
    *,
    message: ParsedEmailMessage,
    processed_at: datetime,
    action: str,
    status: str,
    rejection_reason: str | None = None,
) -> OrganizerInstruction:
    return OrganizerInstruction(
        id=new_id(), source_message_key=gmail_message_key(message.message_id),
        sender_email=message.sender_email.strip().lower(), subject=message.subject,
        received_at=message.sent_at or processed_at, action=action, status=status,
        processed_at=processed_at, rejection_reason=rejection_reason,
    )


def _outcome_message(
    *, instruction: OrganizerInstruction, message: ParsedEmailMessage, recipient: str | None,
    processed_at: datetime, body: str,
) -> OutboundMessage | None:
    if recipient is None:
        return None
    return OutboundMessage(
        id=new_id(), idempotency_key=f"answer-outcome:{message.message_id}",
        message_type="organizer_instruction_outcome", recipient=recipient,
        subject="QOTD Answer instruction result", body_text=body, status=OUTBOUND_PENDING,
        created_at=processed_at, organizer_instruction_id=instruction.id,
    )


def _applied_body(*, game_day: date, correct_option: str, source_url: str) -> str:
    return (
        "Applied Answer instruction.\n\n"
        f"Day: {game_day.isoformat()}\nCorrect option: {correct_option}\n"
        f"Source URL: {source_url}\nIdempotency key: Gmail message identity\n"
    )


def _rejection_body(*, message: ParsedEmailMessage, reason: str) -> str:
    return (
        "Answer instruction rejected.\n\n"
        f"Message: {message.message_id}\nReason: {reason}\n\n"
        "Expected template:\nAction: set-answer\nDay: 2026-07-08\n"
        f"Correct option: C\nSource URL: {ANSWER_TEMPLATE_SOURCE_URL}\n"
    )


def _action_from_message(body_text: str) -> str:
    """Return an action label for a malformed Organizer Instruction."""

    for line in body_text.splitlines():
        name, separator, value = line.partition(":")
        if separator and name.strip().casefold() == "action":
            return value.strip().casefold() or "unknown"
    return "unknown"
