from datetime import UTC, datetime

from qotd.external.email.core import ParsedEmailMessage
from qotd.usecases.handle_answer import apply_answer_instruction
from qotd.usecases.set_answer import ANSWER_INSTRUCTION_QUERY, ProcessSetAnswerEmailsConfig, process_set_answer_emails
from tests.support import InMemoryCanonicalState


def _message(body_text: str, message_id: str = "answer-1") -> ParsedEmailMessage:
    return ParsedEmailMessage(
        message_id=message_id,
        thread_id="thread-1",
        sender_email="organizer@example.com",
        subject="Answer for August 10",
        sent_at=datetime(2026, 8, 9, tzinfo=UTC),
        body_text=body_text,
    )


def test_handle_answer_creates_pending_game_before_manual_publication() -> None:
    result = apply_answer_instruction(
        state=InMemoryCanonicalState(),
        message=_message(
            "Action: set-answer\nDay: 2026-08-10\nCorrect option: B\nSource URL: https://example.com/source"
        ),
        processed_at=datetime(2026, 8, 9, 1, tzinfo=UTC),
    )

    assert result.game is not None
    assert result.game.status == "pending"
    assert result.game.correct_option == "B"
    assert result.game.answer_instruction_id == result.instruction.id


def test_answer_instruction_commits_its_outcome_intent_with_the_game() -> None:
    state = InMemoryCanonicalState()

    result = apply_answer_instruction(
        state=state,
        message=_message(
            "Action: set-answer\nDay: 2026-08-10\nCorrect option: B\nSource URL: https://example.com/source"
        ),
        processed_at=datetime(2026, 8, 9, 1, tzinfo=UTC),
        outcome_recipient="organizer@example.com",
    )

    assert result.outbound_message is not None
    assert result.outbound_message.organizer_instruction_id == result.instruction.id
    assert len(state.outbound_messages) == 1


def test_rejected_answer_instruction_commits_its_outcome_intent() -> None:
    state = InMemoryCanonicalState()

    result = apply_answer_instruction(
        state=state,
        message=_message("Action: set-answer\nDay: 2026-08-10"),
        processed_at=datetime(2026, 8, 9, 1, tzinfo=UTC),
        outcome_recipient="organizer@example.com",
    )

    assert result.instruction.status == "rejected"
    assert result.outbound_message is not None
    assert result.outbound_message.organizer_instruction_id == result.instruction.id


def test_answer_instruction_records_a_conflicting_second_answer_as_rejected() -> None:
    state = InMemoryCanonicalState()
    apply_answer_instruction(
        state=state,
        message=_message(
            "Action: set-answer\nDay: 2026-08-10\nCorrect option: A\nSource URL: https://example.com/source"
        ),
        processed_at=datetime(2026, 8, 9, tzinfo=UTC),
    )

    result = apply_answer_instruction(
        state=state,
        message=_message(
            "Action: set-answer\nDay: 2026-08-10\nCorrect option: B\nSource URL: https://example.com/source",
            message_id="answer-2",
        ),
        processed_at=datetime(2026, 8, 9, 1, tzinfo=UTC),
    )

    assert result.game is None
    assert result.instruction.status == "rejected"
    assert "conflicts" in (result.instruction.rejection_reason or "")
    assert state.find_game(day=datetime(2026, 8, 10, tzinfo=UTC).date()).correct_option == "A"  # type: ignore[union-attr]


def test_malformed_answer_instruction_is_durably_rejected() -> None:
    state = InMemoryCanonicalState()

    result = apply_answer_instruction(
        state=state,
        message=_message(
            "Action: set-answer\nDay: 2026-08-10\nCorrect option: A\nCorrect option: B"
        ),
        processed_at=datetime(2026, 8, 9, tzinfo=UTC),
    )

    assert result.game is None
    assert result.instruction.status == "rejected"
    assert len(state.instructions) == 1


def test_duplicate_answer_instruction_is_an_idempotent_skip() -> None:
    state = InMemoryCanonicalState()
    message = _message(
        "Action: set-answer\nDay: 2026-08-10\nCorrect option: A\nSource URL: https://example.com/source"
    )

    first = apply_answer_instruction(state=state, message=message, processed_at=datetime(2026, 8, 9, tzinfo=UTC))
    duplicate = apply_answer_instruction(state=state, message=message, processed_at=datetime(2026, 8, 9, 1, tzinfo=UTC))

    assert first.instruction.status == "applied"
    assert duplicate.instruction.status == "duplicate"
    assert duplicate.game == first.game


def test_answer_instruction_and_game_roll_back_together_on_storage_failure() -> None:
    class FailingState(InMemoryCanonicalState):
        def set_answer(self, game):  # type: ignore[no-untyped-def]
            raise RuntimeError("storage failure")

    state = FailingState()

    try:
        apply_answer_instruction(
            state=state,
            message=_message(
                "Action: set-answer\nDay: 2026-08-10\nCorrect option: A\nSource URL: https://example.com/source"
            ),
            processed_at=datetime(2026, 8, 9, tzinfo=UTC),
        )
    except RuntimeError as exc:
        assert str(exc) == "storage failure"
    else:
        raise AssertionError("expected storage failure")

    assert state.instructions == {}
    assert state.games == {}
    assert state.series == {}


def test_legacy_answer_action_is_discovered_and_durably_rejected() -> None:
    state = InMemoryCanonicalState()
    queries: list[str] = []

    def fetch_messages(query: str) -> list[ParsedEmailMessage]:
        queries.append(query)
        return [
            _message(
                "Action: set-correct-answer\nDay: 2026-08-10\nCorrect option: A\n"
                "Source URL: https://example.com/source"
            )
        ]

    result = process_set_answer_emails(
        ProcessSetAnswerEmailsConfig(
            sender="sender@example.com",
            gmail_user="sender@example.com",
            organizer_emails=("organizer@example.com",),
            oauth_client_id="client-id",
            oauth_client_secret="client-secret",
            oauth_refresh_token="refresh-token",
            state_store=state,
            dry_run=True,
        ),
        fetch_messages=fetch_messages,
    )

    assert queries == [ANSWER_INSTRUCTION_QUERY]
    assert result.processed[0].accepted is False
    instruction = next(iter(state.instructions.values()))
    assert instruction.status == "rejected"
    assert instruction.action == "set-correct-answer"
