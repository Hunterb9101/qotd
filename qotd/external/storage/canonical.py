"""Intent-level storage contract for canonical QOTD state."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date, datetime

from qotd.domain.canonical import (
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
    def create_or_find_series(self, *, name: str, starts_on: date, ends_on: date) -> Series: ...

    @abstractmethod
    def record_organizer_instruction(self, instruction: OrganizerInstruction) -> OrganizerInstruction: ...

    @abstractmethod
    def record_submission(self, submission: Submission) -> Submission: ...

    @abstractmethod
    def find_game(self, *, day: date) -> Game | None: ...

    @abstractmethod
    def find_latest_answered_game_before(self, *, day: date) -> Game | None: ...

    @abstractmethod
    def publish_game(self, game: Game, *, outbound_message: OutboundMessage | None = None) -> Game: ...

    @abstractmethod
    def discard_pending_game(self, *, day: date) -> None: ...

    @abstractmethod
    def replace_pending_game(self, game: Game, *, outbound_message: OutboundMessage | None = None) -> Game: ...

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
    def record_outbound_message(self, message: OutboundMessage) -> OutboundMessage: ...

    @abstractmethod
    def reconcile_outbound_message(
        self, *, idempotency_key: str, source_message_key: str, sent_at: datetime
    ) -> OutboundMessage: ...

    @abstractmethod
    def read_scoreboard(self, *, series_id: str) -> tuple[ScoreboardEntry, ...]: ...
