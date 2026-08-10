from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
import re

from qotd.domain.canonical import (
    GAME_PUBLISHED,
    GAME_SCORED,
    INSTRUCTION_DUPLICATE,
    OUTBOUND_SENT,
    Game,
    OrganizerInstruction,
    OutboundMessage,
    Player,
    ScoreEvent,
    ScoreboardEntry,
    Series,
    Submission,
    new_id,
)
from qotd.external.email.core import ParsedEmailMessage
from qotd.external.storage.canonical import CanonicalState


class FixedClock:
    """Deterministic source of workflow timestamps for business-flow tests."""

    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


class InMemoryMailbox:
    """Complete parsed-email fixtures with the predicates used by QOTD workflows."""

    def __init__(self, messages: list[ParsedEmailMessage] | None = None) -> None:
        self.messages = messages or []
        self.sent: list[ParsedEmailMessage] = []
        self.unread_message_ids = {message.message_id for message in self.messages}

    def search(self, query: str) -> list[ParsedEmailMessage]:
        """Return messages matching QOTD's subject, sender, and unread predicates."""

        matches = list(self.messages)
        sender = re.search(r"(?:^|\s)from:([^\s]+)", query)
        if sender:
            matches = [message for message in matches if message.sender_email == sender.group(1)]
        subject = re.search(r'subject:"([^"]+)"', query)
        if subject:
            matches = [message for message in matches if subject.group(1) in message.subject]
        if "is:unread" in query:
            matches = [message for message in matches if message.message_id in self.unread_message_ids]
        return matches

    def send(self, message: ParsedEmailMessage) -> str:
        self.sent.append(message)
        return message.message_id

    def mark_read(self, message_id: str) -> None:
        self.unread_message_ids.discard(message_id)


class InMemoryCanonicalState(CanonicalState):
    """Stateful canonical storage implementation for business-flow tests."""

    def __init__(self, *, clock: FixedClock | None = None) -> None:
        self.players: dict[str, Player] = {}
        self.series: dict[str, Series] = {}
        self.games: dict[str, Game] = {}
        self.instructions: dict[str, OrganizerInstruction] = {}
        self.submissions: dict[str, Submission] = {}
        self.score_events: dict[str, ScoreEvent] = {}
        self.outbound_messages: dict[str, OutboundMessage] = {}
        self.clock = clock or FixedClock(datetime(2026, 1, 1, tzinfo=UTC))

    def create_or_find_player(self, *, email: str) -> Player:
        normalized = email.strip().lower()
        for player in self.players.values():
            if player.email == normalized:
                return player
        player = Player(id=new_id(), email=normalized)
        self.players[player.id] = player
        return player

    def create_or_find_series(self, *, name: str, starts_on: date, ends_on: date) -> Series:
        for series in self.series.values():
            if series.name == name:
                return series
        now = self.clock.now()
        series = Series(new_id(), name, starts_on, ends_on, now, now)
        self.series[series.id] = series
        return series

    def record_organizer_instruction(self, instruction: OrganizerInstruction) -> OrganizerInstruction:
        for existing in self.instructions.values():
            if existing.source_message_key == instruction.source_message_key:
                return replace(existing, status=INSTRUCTION_DUPLICATE)
        self.instructions[instruction.id] = instruction
        return instruction

    def record_answer_instruction(
        self,
        *,
        instruction: OrganizerInstruction,
        series: Series,
        game: Game,
        outbound_message: OutboundMessage | None = None,
    ) -> tuple[OrganizerInstruction, Game]:
        """Atomically record an Answer Instruction and its pending Game."""

        existing_instruction = self.find_organizer_instruction(source_message_key=instruction.source_message_key)
        if existing_instruction is not None:
            existing_game = next(
                (item for item in self.games.values() if item.answer_instruction_id == existing_instruction.id),
                self.find_game(day=game.day),
            )
            if existing_game is None:
                raise RuntimeError("Answer Instruction committed without its Game")
            return replace(existing_instruction, status=INSTRUCTION_DUPLICATE), existing_game

        series_before, games_before, instructions_before = self.series.copy(), self.games.copy(), self.instructions.copy()
        try:
            existing_series = next((item for item in self.series.values() if item.name == series.name), None)
            recorded_series = existing_series or series
            recorded_game = self.set_answer(replace(game, series_id=recorded_series.id))
            self.series.setdefault(recorded_series.id, recorded_series)
            self.instructions[instruction.id] = instruction
            if outbound_message is not None:
                self.record_outbound_message(outbound_message)
            return instruction, recorded_game
        except Exception:
            self.series, self.games, self.instructions = series_before, games_before, instructions_before
            raise

    def record_organizer_instruction_outcome(
        self, *, instruction: OrganizerInstruction, outbound_message: OutboundMessage
    ) -> OrganizerInstruction:
        """Atomically record a rejected Instruction and its outcome intent."""

        existing = self.find_organizer_instruction(source_message_key=instruction.source_message_key)
        if existing is not None:
            self.record_outbound_message(outbound_message)
            return replace(existing, status=INSTRUCTION_DUPLICATE)
        instructions_before, outbound_before = self.instructions.copy(), self.outbound_messages.copy()
        try:
            self.instructions[instruction.id] = instruction
            self.record_outbound_message(outbound_message)
            return instruction
        except Exception:
            self.instructions, self.outbound_messages = instructions_before, outbound_before
            raise

    def find_organizer_instruction(self, *, source_message_key: str) -> OrganizerInstruction | None:
        return next(
            (item for item in self.instructions.values() if item.source_message_key == source_message_key), None
        )

    def record_submission(self, submission: Submission) -> Submission:
        for existing in self.submissions.values():
            if existing.source_message_key == submission.source_message_key:
                return existing
        game = self.games[submission.game_id]
        if submission.received_at >= game.deadline_at:
            recorded = replace(submission, is_eligible=False, ineligibility_reason="late")
        else:
            recorded = replace(submission, is_eligible=True, ineligibility_reason=None)
        self.submissions[recorded.id] = recorded
        eligible = [
            item for item in self.submissions.values()
            if item.game_id == recorded.game_id and item.player_id == recorded.player_id
            and item.received_at < game.deadline_at
        ]
        if not eligible:
            return recorded
        selected = max(eligible, key=lambda item: (item.received_at, item.source_message_key))
        for item in eligible:
            self.submissions[item.id] = replace(
                item, is_eligible=item.id == selected.id,
                ineligibility_reason=None if item.id == selected.id else "superseded",
            )
        return self.submissions[recorded.id]

    def find_game(self, *, day: date) -> Game | None:
        return next((game for game in self.games.values() if game.day == day), None)

    def find_latest_answered_game_before(self, *, day: date) -> Game | None:
        games = [game for game in self.games.values() if game.day < day and game.correct_option is not None]
        return max(games, key=lambda game: game.day, default=None)

    def find_latest_scored_game_before(self, *, day: date) -> Game | None:
        games = [
            game for game in self.games.values()
            if game.day < day and game.status == GAME_SCORED and game.correct_option is not None
        ]
        return max(games, key=lambda game: game.day, default=None)

    def find_games_between(self, *, starts_on: date, ends_on: date) -> tuple[Game, ...]:
        return tuple(game for game in self.games.values() if starts_on <= game.day <= ends_on)

    def publish_game(self, game: Game, *, outbound_message: OutboundMessage | None = None) -> Game:
        for existing in self.games.values():
            if existing.day == game.day:
                if existing.status != "pending":
                    return existing
                published = replace(
                    game,
                    id=existing.id,
                    status=GAME_PUBLISHED,
                    created_at=existing.created_at,
                    correct_option=existing.correct_option or game.correct_option,
                    answer_source_url=existing.answer_source_url or game.answer_source_url,
                    answer_source_note=existing.answer_source_note or game.answer_source_note,
                    answer_instruction_id=existing.answer_instruction_id or game.answer_instruction_id,
                )
                self.games[published.id] = published
                if outbound_message is not None:
                    self.record_outbound_message(outbound_message)
                return published
        published = replace(game, status=GAME_PUBLISHED)
        self.games[published.id] = published
        if outbound_message is not None:
            self.record_outbound_message(outbound_message)
        return published

    def discard_pending_game(self, *, day: date) -> None:
        for game_id, game in tuple(self.games.items()):
            if game.day == day and game.status == "pending":
                del self.games[game_id]

    def replace_pending_game(self, game: Game, *, outbound_message: OutboundMessage | None = None) -> Game:
        self.discard_pending_game(day=game.day)
        return self.publish_game(game, outbound_message=outbound_message)

    def set_answer(self, game: Game) -> Game:
        current = self.games.get(game.id)
        if current is None:
            current = next((item for item in self.games.values() if item.day == game.day), None)
        if current is None:
            pending = replace(game, status="pending")
            self.games[pending.id] = pending
            return pending
        if current.correct_option is not None:
            if current.correct_option != game.correct_option:
                raise ValueError("Game Answer conflicts with the existing Answer")
            return current
        updated = replace(current, correct_option=game.correct_option, answer_source_url=game.answer_source_url,
                          answer_source_note=game.answer_source_note, answer_instruction_id=game.answer_instruction_id)
        self.games[updated.id] = updated
        return updated

    def score_game(
        self,
        game: Game,
        *,
        score_events: tuple[ScoreEvent, ...] = (),
        outbound_messages: tuple[OutboundMessage, ...] = (),
    ) -> Game:
        current = self.games[game.id]
        if current.status == GAME_SCORED:
            return current
        if current.status != GAME_PUBLISHED:
            raise ValueError("Only a published Game can be scored")
        if current.correct_option is None:
            raise ValueError("A Game needs an Answer before scoring")
        for event in score_events:
            if event.game_id != current.id or event.event_type != "automatic":
                raise ValueError("Automatic Score Events must belong to the scored Game")
            submission = self.submissions.get(event.submission_id or "")
            if (
                submission is None
                or submission.game_id != current.id
                or submission.player_id != event.player_id
                or not submission.is_eligible
                or submission.ineligibility_reason is not None
            ):
                raise ValueError("Automatic Score Events must use the selected eligible Submission")
        if any(event.idempotency_key in {item.idempotency_key for item in self.score_events.values()} for event in score_events):
            return current
        scored = replace(current, status=GAME_SCORED, scored_at=game.scored_at)
        self.games[scored.id] = scored
        for event in score_events:
            self.score_events[event.id] = event
        for message in outbound_messages:
            self.record_outbound_message(message)
        return scored

    def record_manual_score_event(self, event: ScoreEvent) -> ScoreEvent:
        for existing in self.score_events.values():
            if existing.idempotency_key == event.idempotency_key:
                return existing
        self.score_events[event.id] = event
        return event

    def record_instruction_score_event(self, *, instruction: OrganizerInstruction, event: ScoreEvent) -> ScoreEvent:
        recorded = self.record_organizer_instruction(instruction)
        if recorded.status == INSTRUCTION_DUPLICATE:
            return self.record_manual_score_event(event)
        return self.record_manual_score_event(event)

    def record_manual_score_event_instruction(
        self, *, player: Player, instruction: OrganizerInstruction, event: ScoreEvent, outbound_message: OutboundMessage
    ) -> tuple[ScoreEvent, bool]:
        """Atomically persist an Instruction, Manual Score Event, and its outcome intent."""

        existing = self.find_organizer_instruction(source_message_key=instruction.source_message_key)
        if existing is not None:
            existing_event = next(
                (item for item in self.score_events.values() if item.idempotency_key == event.idempotency_key), event
            )
            self.record_outbound_message(outbound_message)
            return existing_event, False
        players_before = self.players.copy()
        instructions_before = self.instructions.copy()
        events_before = self.score_events.copy()
        outbound_before = self.outbound_messages.copy()
        try:
            self.players.setdefault(player.id, player)
            self.instructions[instruction.id] = instruction
            self.score_events[event.id] = event
            self.record_outbound_message(outbound_message)
            return event, True
        except Exception:
            self.players = players_before
            self.instructions = instructions_before
            self.score_events = events_before
            self.outbound_messages = outbound_before
            raise

    def record_outbound_message(self, message: OutboundMessage) -> OutboundMessage:
        for existing in self.outbound_messages.values():
            if existing.idempotency_key == message.idempotency_key:
                return existing
        self.outbound_messages[message.id] = message
        return message

    def find_outbound_message(self, *, idempotency_key: str) -> OutboundMessage | None:
        return next(
            (item for item in self.outbound_messages.values() if item.idempotency_key == idempotency_key), None
        )

    def reconcile_outbound_message(
        self, *, idempotency_key: str, source_message_key: str, sent_at: datetime
    ) -> OutboundMessage:
        message = next(item for item in self.outbound_messages.values() if item.idempotency_key == idempotency_key)
        reconciled = replace(message, status=OUTBOUND_SENT, source_message_key=source_message_key, sent_at=sent_at)
        self.outbound_messages[reconciled.id] = reconciled
        return reconciled

    def read_scoreboard(self, *, series_id: str) -> tuple[ScoreboardEntry, ...]:
        active_player_ids = {
            submission.player_id
            for submission in self.submissions.values()
            if self.games[submission.game_id].series_id == series_id
        }
        scores = {player_id: 0 for player_id in active_player_ids}
        for event in self.score_events.values():
            if event.series_id == series_id:
                scores[event.player_id] = scores.get(event.player_id, 0) + event.points_delta
        return tuple(
            ScoreboardEntry(series_id, player_id, self.players[player_id].email, score)
            for player_id, score in sorted(scores.items(), key=lambda item: (-item[1], self.players[item[0]].email))
        )
