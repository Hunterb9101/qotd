"""Record a manual Score Event from an Organizer Instruction."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from qotd.domain.canonical import SCORE_EVENT_MANUAL, OrganizerInstruction, Player, ScoreEvent, new_id
from qotd.external.storage.canonical import CanonicalState


@dataclass(frozen=True)
class ManualScoreEventRequest:
    """The validated fields for a manual Score Event."""

    player_email: str
    points_delta: int
    reason: str
    series_id: str
    organizer_instruction: OrganizerInstruction
    game_day: date | None = None


def record_score_event(*, state: CanonicalState, request: ManualScoreEventRequest, created_at: datetime) -> ScoreEvent:
    """Idempotently record one manual Score Event and include a new Player in the Scoreboard."""

    if not request.reason.strip():
        raise ValueError("a manual Score Event requires a reason")
    if request.points_delta == 0:
        raise ValueError("a manual Score Event must have a nonzero points delta")
    player = Player(id=new_id(), email=request.player_email.strip().lower())
    game = state.find_game(day=request.game_day) if request.game_day else None
    return state.record_instruction_score_event(
        player=player,
        instruction=request.organizer_instruction,
        event=ScoreEvent(
            id=new_id(),
            idempotency_key=f"manual:{request.organizer_instruction.source_message_key}",
            player_id=player.id,
            series_id=request.series_id,
            event_type=SCORE_EVENT_MANUAL,
            points_delta=request.points_delta,
            created_at=created_at,
            game_id=game.id if game else None,
            organizer_instruction_id=request.organizer_instruction.id,
            reason=request.reason.strip(),
        )
    )
