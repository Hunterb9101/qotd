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
    Game,
    OrganizerInstruction,
    gmail_message_key,
    new_id,
)
from qotd.domain.dates import answer_cutoff_at, next_scoring_day
from qotd.domain.models import OPTION_LABELS
from qotd.external.email.core import ParsedEmailMessage
from qotd.external.storage.canonical import CanonicalState
from qotd.usecases.parse_organizer_instruction import OrganizerInstructionPayload, parse_organizer_instruction_payload


@dataclass(frozen=True)
class AnswerInstructionResult:
    """The Organizer Instruction and Game produced by an Answer request."""

    instruction: OrganizerInstruction
    game: Game | None


def apply_answer_instruction(
    *, state: CanonicalState, message: ParsedEmailMessage, processed_at: datetime
) -> AnswerInstructionResult:
    """Apply one canonical `set-answer` Organizer Instruction idempotently."""

    try:
        payload = parse_organizer_instruction_payload(message.body_text)
        if payload.action != "set-answer":
            raise ValueError("Organizer Instruction Action must be set-answer")
        return _apply_validated_answer_instruction(
            state=state, message=message, processed_at=processed_at, payload=payload
        )
    except ValueError as exc:
        return AnswerInstructionResult(
            instruction=_record_instruction(
                state=state,
                message=message,
                processed_at=processed_at,
                action=_action_from_message(message.body_text),
                status=INSTRUCTION_REJECTED,
                rejection_reason=str(exc),
            ),
            game=None,
        )


def _apply_validated_answer_instruction(
    *, state: CanonicalState, message: ParsedEmailMessage, processed_at: datetime, payload: OrganizerInstructionPayload
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

    instruction = _record_instruction(
        state=state, message=message, processed_at=processed_at, action=payload.action, status=INSTRUCTION_APPLIED
    )
    if instruction.status != INSTRUCTION_APPLIED:
        existing = state.find_game(day=game_day)
        return AnswerInstructionResult(instruction=instruction, game=existing)

    days_in_month = calendar.monthrange(game_day.year, game_day.month)[1]
    series = state.create_or_find_series(
        name=game_day.strftime("%Y-%m"),
        starts_on=game_day.replace(day=1),
        ends_on=game_day.replace(day=days_in_month),
    )
    game = state.set_answer(
        Game(
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
    )
    return AnswerInstructionResult(instruction=instruction, game=game)


def _record_instruction(
    *,
    state: CanonicalState,
    message: ParsedEmailMessage,
    processed_at: datetime,
    action: str,
    status: str,
    rejection_reason: str | None = None,
) -> OrganizerInstruction:
    return state.record_organizer_instruction(
        OrganizerInstruction(
            id=new_id(),
            source_message_key=gmail_message_key(message.message_id),
            sender_email=message.sender_email.strip().lower(),
            subject=message.subject,
            received_at=message.sent_at or processed_at,
            action=action,
            status=status,
            processed_at=processed_at,
            rejection_reason=rejection_reason,
        )
    )


def _action_from_message(body_text: str) -> str:
    """Return an action label for a malformed Organizer Instruction."""

    for line in body_text.splitlines():
        name, separator, value = line.partition(":")
        if separator and name.strip().casefold() == "action":
            return value.strip().casefold() or "unknown"
    return "unknown"
