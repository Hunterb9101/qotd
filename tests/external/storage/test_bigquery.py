from __future__ import annotations

import inspect
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from datetime import UTC, date, datetime

from qotd.domain.canonical import GAME_PENDING, GAME_PUBLISHED, OUTBOUND_PENDING, Game, OrganizerInstruction, OutboundMessage, ScoreEvent, Series, Submission
from qotd.external.storage.bigquery import BQAdapter, MAX_TRANSACTION_ATTEMPTS


class FakeResult:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows

    def result(self) -> list[dict[str, object]]:
        return self.rows


class FakeClient:
    def __init__(self, outcomes: list[object]) -> None:
        self.outcomes = outcomes
        self.calls: list[tuple[str, object]] = []

    def query(self, sql: str, *, job_config: object) -> FakeResult:
        self.calls.append((sql, job_config))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return FakeResult(outcome)  # type: ignore[arg-type]


class FakeScalarQueryParameter:
    def __init__(self, name: str, parameter_type: str, value: object) -> None:
        self.name = name
        self.parameter_type = parameter_type
        self.value = value


def test_transaction_rows_uses_parameter_binding_and_a_transaction_script() -> None:
    client = FakeClient([[{"id": "player-1"}]])
    adapter = BQAdapter(project_id="project-id", dataset="qotd", client=client)
    parameter = object()
    fake_bigquery = SimpleNamespace(QueryJobConfig=lambda **kwargs: kwargs)

    with patch("qotd.external.storage.bigquery.importlib.import_module", return_value=fake_bigquery):
        rows = adapter.transaction_rows("UPDATE players SET email = @email", [parameter])

    assert rows == [{"id": "player-1"}]
    sql, config = client.calls[0]
    assert isinstance(config, dict)
    assert sql.startswith("BEGIN TRANSACTION;")
    assert sql.endswith("COMMIT TRANSACTION;")
    assert config["query_parameters"] == [parameter]
    assert "player-1" not in sql


def test_transaction_rows_retries_only_transaction_conflicts() -> None:
    client = FakeClient([RuntimeError("Concurrent update cancelled"), []])
    adapter = BQAdapter(project_id="project-id", dataset="qotd", client=client)
    fake_bigquery = SimpleNamespace(QueryJobConfig=lambda **kwargs: kwargs)

    with patch("qotd.external.storage.bigquery.importlib.import_module", return_value=fake_bigquery):
        assert adapter.transaction_rows("UPDATE games SET status = @status", []) == []

    assert len(client.calls) == 2


def test_transaction_rows_surfaces_exhausted_conflicts() -> None:
    client = FakeClient([RuntimeError("Concurrent update cancelled")] * MAX_TRANSACTION_ATTEMPTS)
    adapter = BQAdapter(project_id="project-id", dataset="qotd", client=client)
    fake_bigquery = SimpleNamespace(QueryJobConfig=lambda **kwargs: kwargs)

    with patch("qotd.external.storage.bigquery.importlib.import_module", return_value=fake_bigquery):
        with pytest.raises(RuntimeError, match="canonical-state transaction failed"):
            adapter.transaction_rows("UPDATE games SET status = @status", [])

    assert len(client.calls) == MAX_TRANSACTION_ATTEMPTS


def test_create_or_find_player_uses_a_parameterized_idempotent_merge() -> None:
    client = FakeClient([[{"id": "player-1", "email": "ada@example.com", "nickname": None}]])
    adapter = BQAdapter(project_id="project-id", dataset="qotd", client=client)
    fake_bigquery = SimpleNamespace(
        QueryJobConfig=lambda **kwargs: kwargs,
        ScalarQueryParameter=FakeScalarQueryParameter,
    )

    with patch("qotd.external.storage.bigquery.importlib.import_module", return_value=fake_bigquery):
        player = adapter.create_or_find_player(email=" Ada@Example.com ")

    assert player.email == "ada@example.com"
    sql, config = client.calls[0]
    assert "MERGE `project-id.qotd.players`" in sql
    assert "@email" in sql
    assert "ada@example.com" not in sql
    assert isinstance(config, dict)
    assert any(parameter.value == "ada@example.com" for parameter in config["query_parameters"])


def test_create_or_find_series_reads_the_committed_row_when_a_transaction_returns_no_rows() -> None:
    client = FakeClient([[], [{"id": "series-1", "name": "2026-08", "starts_on": date(2026, 8, 1), "ends_on": date(2026, 8, 31), "created_at": datetime(2026, 8, 1, tzinfo=UTC), "updated_at": datetime(2026, 8, 1, tzinfo=UTC)}]])
    adapter = BQAdapter(project_id="project-id", dataset="qotd", client=client)
    fake_bigquery = SimpleNamespace(QueryJobConfig=lambda **kwargs: kwargs, ScalarQueryParameter=FakeScalarQueryParameter)

    with patch("qotd.external.storage.bigquery.importlib.import_module", return_value=fake_bigquery):
        series = adapter.create_or_find_series(name="2026-08", starts_on=date(2026, 8, 1), ends_on=date(2026, 8, 31))

    assert series.id == "series-1"
    assert "WHERE name = @name" in client.calls[1][0]


def test_record_submission_classifies_deadline_and_supersession_in_one_transaction() -> None:
    client = FakeClient([[]])
    adapter = BQAdapter(project_id="project-id", dataset="qotd", client=client)
    fake_bigquery = SimpleNamespace(QueryJobConfig=lambda **kwargs: kwargs, ScalarQueryParameter=FakeScalarQueryParameter)
    now = datetime(2026, 8, 11, tzinfo=UTC)
    submission = Submission("submission-1", "message-key", "game-1", "player-1", "A", now, True, now, now)

    with patch("qotd.external.storage.bigquery.importlib.import_module", return_value=fake_bigquery):
        adapter.record_submission(submission)

    sql, _ = client.calls[0]
    assert "BEGIN TRANSACTION;" in sql
    assert "item.received_at < game.deadline_at" in sql
    assert "'late'" in sql
    assert "'superseded'" in sql
    assert "prior.source_message_key < current.source_message_key" in sql
    assert "later.source_message_key > current.source_message_key" in sql


def test_score_game_writes_game_events_and_outbound_intents_in_one_transaction() -> None:
    client = FakeClient([[]])
    adapter = BQAdapter(project_id="project-id", dataset="qotd", client=client)
    fake_bigquery = SimpleNamespace(
        QueryJobConfig=lambda **kwargs: kwargs,
        ScalarQueryParameter=FakeScalarQueryParameter,
    )
    now = datetime(2026, 8, 11, tzinfo=UTC)
    game = Game("game-1", "series-1", date(2026, 8, 10), GAME_PUBLISHED, "manual", now, now, now, correct_option="A")
    event = ScoreEvent("event-1", "event-key", "player-1", "series-1", "automatic", 1, now, game_id="game-1", submission_id="submission-1")

    with patch("qotd.external.storage.bigquery.importlib.import_module", return_value=fake_bigquery):
        adapter.score_game(game, score_events=(event,))

    sql, config = client.calls[0]
    assert sql.count("BEGIN TRANSACTION;") == 1
    assert "UPDATE `project-id.qotd.games`" in sql
    assert "INSERT INTO `project-id.qotd.score_events`" in sql
    assert "SET transitioned = @@row_count = 1" in sql
    assert "DECLARE events_valid BOOL DEFAULT TRUE" in sql
    assert "`project-id.qotd.submissions`" in sql
    assert "AND is_eligible" in sql
    assert "@event_0_event_type = 'automatic'" in sql
    assert "@event_0_series_id" in sql
    assert "WHERE transitioned" in sql
    assert "@event_0_idempotency_key" in sql
    assert "event-key" not in sql
    assert isinstance(config, dict)


def test_record_answer_instruction_writes_instruction_series_and_game_in_one_transaction() -> None:
    now = datetime(2026, 8, 9, tzinfo=UTC)
    instruction = OrganizerInstruction(
        "instruction-1", "message-key", "organizer@example.com", "Answer", now, "set-answer", "applied", now
    )
    series = Series("series-1", "2026-08", date(2026, 8, 1), date(2026, 8, 31), now, now)
    game = Game(
        "game-1", series.id, date(2026, 8, 10), GAME_PENDING, "manual", now, now, now,
        correct_option="A", answer_instruction_id=instruction.id,
    )
    outbound = OutboundMessage(
        "outbound-1", "answer-outcome:message-key", "organizer_instruction_outcome", "organizer@example.com",
        "QOTD Answer instruction result", "Applied Answer instruction.", OUTBOUND_PENDING, now,
        organizer_instruction_id=instruction.id,
    )
    client = FakeClient([[], [instruction.__dict__]])
    adapter = BQAdapter(project_id="project-id", dataset="qotd", client=client)
    fake_bigquery = SimpleNamespace(
        QueryJobConfig=lambda **kwargs: kwargs,
        ScalarQueryParameter=FakeScalarQueryParameter,
    )

    with patch("qotd.external.storage.bigquery.importlib.import_module", return_value=fake_bigquery):
        recorded_instruction, recorded_game = adapter.record_answer_instruction(
            instruction=instruction, series=series, game=game, outbound_message=outbound
        )

    sql, _ = client.calls[0]
    assert sql.count("BEGIN TRANSACTION;") == 1
    assert "MERGE `project-id.qotd.organizer_instructions`" in sql
    assert "MERGE `project-id.qotd.series`" in sql
    assert "MERGE `project-id.qotd.games`" in sql
    assert "INSERT INTO `project-id.qotd.outbound_messages`" in sql
    assert "WHERE instruction_is_new" in sql
    assert "instruction_is_new" in sql
    assert recorded_instruction == instruction
    assert recorded_game == game


def test_canonical_mutations_do_not_delegate_to_append_load_jobs() -> None:
    mutations = (
        BQAdapter.create_or_find_player,
        BQAdapter.create_or_find_series,
        BQAdapter.record_organizer_instruction,
        BQAdapter.record_answer_instruction,
        BQAdapter.record_organizer_instruction_outcome,
        BQAdapter.record_submission,
        BQAdapter.publish_game,
        BQAdapter.set_answer,
        BQAdapter.score_game,
        BQAdapter.record_manual_score_event,
        BQAdapter.record_outbound_message,
        BQAdapter.reconcile_outbound_message,
    )

    for mutation in mutations:
        source = inspect.getsource(mutation)
        assert "insert_rows" not in source
        assert "WRITE_APPEND" not in source
