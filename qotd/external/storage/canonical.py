"""Intent-level storage contract for canonical QOTD state."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date, datetime

from qotd.domain.canonical import (
    AICall,
    Game,
    OrganizerInstruction,
    OutboundMessage,
    Player,
    ScoreEvent,
    ScoreboardEntry,
    Series,
    Submission,
)


class CanonicalState(ABC):
    """Persistent operations required by the canonical Game lifecycle."""

    @abstractmethod
    def create_or_find_player(self, *, email: str) -> Player: ...

    @abstractmethod
    def record_ai_call(self, ai_call: AICall) -> AICall: ...

    @abstractmethod
    def create_or_find_series(self, *, name: str, starts_on: date, ends_on: date) -> Series: ...

    @abstractmethod
    def record_organizer_instruction(self, instruction: OrganizerInstruction) -> OrganizerInstruction: ...

    @abstractmethod
    def record_answer_instruction(
        self,
        *,
        instruction: OrganizerInstruction,
        series: Series,
        game: Game,
        outbound_message: OutboundMessage | None = None,
    ) -> tuple[OrganizerInstruction, Game]: ...

    @abstractmethod
    def record_organizer_instruction_outcome(
        self, *, instruction: OrganizerInstruction, outbound_message: OutboundMessage
    ) -> OrganizerInstruction: ...

    @abstractmethod
    def find_organizer_instruction(self, *, source_message_key: str) -> OrganizerInstruction | None: ...

    @abstractmethod
    def record_submission(self, submission: Submission) -> Submission: ...

    @abstractmethod
    def find_game(self, *, day: date) -> Game | None: ...

    @abstractmethod
    def find_latest_answered_game_before(self, *, day: date) -> Game | None: ...

    @abstractmethod
    def find_latest_scored_game_before(self, *, day: date) -> Game | None: ...

    @abstractmethod
    def find_games_between(self, *, starts_on: date, ends_on: date) -> tuple[Game, ...]: ...

    @abstractmethod
    def publish_game(
        self, game: Game, *, series: Series | None = None, outbound_message: OutboundMessage | None = None
    ) -> Game: ...

    @abstractmethod
    def discard_pending_game(self, *, day: date) -> None: ...

    @abstractmethod
    def replace_pending_game(
        self, game: Game, *, series: Series | None = None, outbound_message: OutboundMessage | None = None
    ) -> Game: ...

    @abstractmethod
    def set_answer(self, game: Game) -> Game: ...

    @abstractmethod
    def score_game(
        self,
        game: Game,
        *,
        score_events: tuple[ScoreEvent, ...] = (),
        outbound_messages: tuple[OutboundMessage, ...] = (),
    ) -> Game: ...

    @abstractmethod
    def record_manual_score_event(self, event: ScoreEvent) -> ScoreEvent: ...

    @abstractmethod
    def record_instruction_score_event(
        self, *, player: Player, instruction: OrganizerInstruction, event: ScoreEvent
    ) -> ScoreEvent: ...

    @abstractmethod
    def record_manual_score_event_instruction(
        self,
        *,
        player: Player,
        instruction: OrganizerInstruction,
        event: ScoreEvent,
        outbound_message: OutboundMessage,
    ) -> tuple[ScoreEvent, bool]: ...

    @abstractmethod
    def record_outbound_message(self, message: OutboundMessage) -> OutboundMessage: ...

    @abstractmethod
    def find_outbound_message(self, *, idempotency_key: str) -> OutboundMessage | None: ...

    @abstractmethod
    def reconcile_outbound_message(
        self, *, idempotency_key: str, source_message_key: str, sent_at: datetime
    ) -> OutboundMessage: ...

    @abstractmethod
    def read_scoreboard(self, *, series_id: str) -> tuple[ScoreboardEntry, ...]: ...
