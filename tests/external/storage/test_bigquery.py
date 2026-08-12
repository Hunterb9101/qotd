from __future__ import annotations

import inspect
import calendar
import importlib
import os
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch
from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

import pytest

from datetime import UTC, date, datetime

from qotd.domain.canonical import GAME_PENDING, GAME_PUBLISHED, GAME_SCORED, INSTRUCTION_APPLIED, OUTBOUND_PENDING, OUTBOUND_SENT, PUBLICATION_AUTOMATED, SCORE_EVENT_AUTOMATIC, SCORE_EVENT_MANUAL, Game, OrganizerInstruction, OutboundMessage, Player, ScoreEvent, Series, Submission, new_id
from qotd.external.storage.bigquery import BQAdapter, MAX_TRANSACTION_ATTEMPTS, build_bigquery_state_store
from qotd.provision import provision_canonical_state


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


def _integration_state():
    required = (
        "QOTD_BIGQUERY_TEST_PROJECT",
        "QOTD_BIGQUERY_TEST_DATASET",
        "GOOGLE_OAUTH_CLIENT_ID",
        "GOOGLE_OAUTH_CLIENT_SECRET",
        "GOOGLE_OAUTH_REFRESH_TOKEN",
    )
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        pytest.fail(
            "Live BigQuery integration tests require: " + ", ".join(missing),
            pytrace=False,
        )

    project_id = os.environ["QOTD_BIGQUERY_TEST_PROJECT"]
    dataset = os.environ["QOTD_BIGQUERY_TEST_DATASET"]
    if not dataset.endswith("_test"):
        pytest.fail("QOTD_BIGQUERY_TEST_DATASET must end in '_test'", pytrace=False)
    state = build_bigquery_state_store(
        project_id=project_id,
        dataset=dataset,
        oauth_client_id=os.environ["GOOGLE_OAUTH_CLIENT_ID"],
        oauth_client_secret=os.environ["GOOGLE_OAUTH_CLIENT_SECRET"],
        oauth_refresh_token=os.environ["GOOGLE_OAUTH_REFRESH_TOKEN"],
    )
    provision_canonical_state(client=state.client, project_id=project_id, dataset=dataset)
    return state


class DryRunBQAdapter(BQAdapter):
    """Validate generated transaction SQL through BigQuery without executing DML."""

    def transaction_rows(self, statement: str, parameters: list[Any]) -> list[dict[str, Any]]:
        bigquery = importlib.import_module("google.cloud.bigquery")
        declarations, transactional_statement = self._split_leading_declarations(statement)
        script = f"{declarations}BEGIN TRANSACTION;\n{transactional_statement}\nCOMMIT TRANSACTION;"
        job_config = bigquery.QueryJobConfig(
            query_parameters=parameters,
            dry_run=True,
            use_query_cache=False,
        )
        list(self.client.query(script, job_config=job_config).result())
        return []

    def query_rows(self, query: str, parameters: list[Any] | None = None) -> list[dict[str, Any]]:
        bigquery = importlib.import_module("google.cloud.bigquery")
        job_config = bigquery.QueryJobConfig(
            query_parameters=parameters or [],
            dry_run=True,
            use_query_cache=False,
        )
        list(self.client.query(query, job_config=job_config).result())
        return []

    def create_or_find_player(self, *, email: str) -> Player:
        self._merge_record(table_name="players", key="email", values={"id": "dry-run-player", "email": email, "nickname": None})
        return Player(id="dry-run-player", email=email)

    def create_or_find_series(self, *, name: str, starts_on: Any, ends_on: Any) -> Series:
        now = datetime(2026, 8, 11, tzinfo=UTC)
        self._merge_record(
            table_name="series", key="name",
            values={"id": "dry-run-series", "name": name, "starts_on": starts_on, "ends_on": ends_on, "created_at": now, "updated_at": now},
        )
        return Series("dry-run-series", name, starts_on, ends_on, now, now)

    def reconcile_outbound_message(
        self, *, idempotency_key: str, source_message_key: str, sent_at: datetime
    ) -> OutboundMessage:
        statement = f"""
            UPDATE `{self.table("outbound_messages")}`
            SET status = 'sent', source_message_key = @source_message_key, sent_at = @sent_at
            WHERE idempotency_key = @idempotency_key AND status = 'pending';
        """
        self.transaction_rows(
            statement,
            self._parameters({"idempotency_key": idempotency_key, "source_message_key": source_message_key, "sent_at": sent_at}),
        )
        return OutboundMessage(
            id="dry-run-outbound", idempotency_key=idempotency_key, message_type="dry-run", recipient="dry-run@example.invalid",
            subject="Dry run", body_text="Dry run", status=OUTBOUND_SENT, created_at=sent_at,
            source_message_key=source_message_key, sent_at=sent_at,
        )


def _dry_run_state() -> DryRunBQAdapter:
    required = (
        "QOTD_BIGQUERY_DRY_RUN_PROJECT",
        "QOTD_BIGQUERY_DRY_RUN_DATASET",
        "GOOGLE_OAUTH_CLIENT_ID",
        "GOOGLE_OAUTH_CLIENT_SECRET",
        "GOOGLE_OAUTH_REFRESH_TOKEN",
    )
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        pytest.fail(
            "BigQuery dry-run validation requires: " + ", ".join(missing),
            pytrace=False,
        )
    state = build_bigquery_state_store(
        project_id=os.environ["QOTD_BIGQUERY_DRY_RUN_PROJECT"],
        dataset=os.environ["QOTD_BIGQUERY_DRY_RUN_DATASET"],
        oauth_client_id=os.environ["GOOGLE_OAUTH_CLIENT_ID"],
        oauth_client_secret=os.environ["GOOGLE_OAUTH_CLIENT_SECRET"],
        oauth_refresh_token=os.environ["GOOGLE_OAUTH_REFRESH_TOKEN"],
    )
    return DryRunBQAdapter(project_id=state.project_id, dataset=state.dataset, client=state.client)


@pytest.mark.intg
def test_bigquery_dry_run_validates_every_canonical_state_query() -> None:
    """Use BigQuery's parser for every canonical read and write path without DML."""

    state = _dry_run_state()
    now = datetime(2026, 8, 11, tzinfo=UTC)

    series = state.create_or_find_series(name="dry-run-series", starts_on=date(2026, 8, 1), ends_on=date(2026, 8, 31))
    player = state.create_or_find_player(email="dry-run@example.invalid")
    game = Game(
        id="dry-run-game", series_id=series.id, day=date(2026, 8, 10), status=GAME_PUBLISHED,
        publication_mode=PUBLICATION_AUTOMATED, question_prompt="Question", question_options={"A": "One"},
        publication_subject="QOTD - 08-10-26", published_at=now, publication_message_key="dry-run-publication",
        deadline_at=now, correct_option="A", answer_source_url="https://example.invalid", created_at=now, updated_at=now,
    )
    instruction = OrganizerInstruction(
        id="dry-run-instruction", source_message_key="dry-run-instruction", sender_email="organizer@example.invalid",
        subject="Instruction", received_at=now, action="set-answer", status=INSTRUCTION_APPLIED, processed_at=now,
    )
    outbound = OutboundMessage(
        id="dry-run-outbound", idempotency_key="dry-run-outbound", message_type="organizer_scoring_update",
        recipient="organizer@example.invalid", subject="Update", body_text="Update", status=OUTBOUND_PENDING, created_at=now, game_id=game.id,
    )
    submission = Submission("dry-run-submission", "dry-run-message", game.id, player.id, "A", now, True, now, now)
    automatic_event = ScoreEvent(
        id="dry-run-automatic-event", idempotency_key="dry-run-automatic-event", player_id=player.id, series_id=series.id,
        event_type=SCORE_EVENT_AUTOMATIC, points_delta=1, created_at=now, game_id=game.id, submission_id=submission.id,
    )
    manual_event = ScoreEvent(
        id="dry-run-manual-event", idempotency_key="dry-run-manual-event", player_id=player.id, series_id=series.id,
        event_type=SCORE_EVENT_MANUAL, points_delta=1, created_at=now, organizer_instruction_id=instruction.id,
    )

    state.record_organizer_instruction(instruction)
    state.record_answer_instruction(instruction=instruction, series=series, game=game, outbound_message=outbound)
    state.record_organizer_instruction_outcome(instruction=instruction, outbound_message=outbound)
    state.record_submission(submission)
    state.publish_game(game, series=series, outbound_message=outbound)
    state.set_answer(game)
    state.discard_pending_game(day=game.day)
    state.replace_pending_game(game, series=series, outbound_message=outbound)
    state.score_game(replace(game, scored_at=now), score_events=(automatic_event,), outbound_messages=(outbound,))
    state.record_manual_score_event(manual_event)
    state.record_instruction_score_event(player=player, instruction=instruction, event=manual_event)
    state.record_manual_score_event_instruction(player=player, instruction=instruction, event=manual_event, outbound_message=outbound)
    state.record_outbound_message(outbound)
    state.reconcile_outbound_message(idempotency_key=outbound.idempotency_key, source_message_key="dry-run-sent", sent_at=now)
    assert state.find_organizer_instruction(source_message_key=instruction.source_message_key) is None
    assert state.find_game(day=game.day) is None
    assert state.find_latest_answered_game_before(day=game.day) is None
    assert state.find_latest_scored_game_before(day=game.day) is None
    assert state.find_games_between(starts_on=game.day, ends_on=game.day) == ()
    assert state.find_outbound_message(idempotency_key=outbound.idempotency_key) is None
    assert state.read_scoreboard(series_id="dry-run-series") == ()


@pytest.mark.intg
def test_bigquery_persists_and_scores_a_player_submission() -> None:
    """Exercise the production SQL against an isolated BigQuery dataset."""

    state = _integration_state()
    run_id = uuid4().hex
    game_day = date(2100, 1, 1) + timedelta(days=int(run_id[:6], 16) % 36500)
    now = datetime.now(UTC)
    series = state.create_or_find_series(
        name=f"integration-{run_id}",
        starts_on=game_day.replace(day=1),
        ends_on=game_day.replace(day=calendar.monthrange(game_day.year, game_day.month)[1]),
    )
    player = state.create_or_find_player(email=f"qotd-integration-{run_id}@example.invalid")
    game = state.publish_game(
        Game(
            id=new_id(),
            series_id=series.id,
            day=game_day,
            status=GAME_PUBLISHED,
            publication_mode=PUBLICATION_AUTOMATED,
            question_prompt="Integration test question",
            question_options={"A": "Correct", "B": "Incorrect", "C": "Incorrect", "D": "Incorrect"},
            publication_subject="QOTD integration test",
            published_at=now,
            publication_message_key=f"integration-publication-{run_id}",
            deadline_at=now + timedelta(hours=1),
            correct_option="A",
            answer_source_url="https://example.invalid/source",
            created_at=now,
            updated_at=now,
        ),
        series=series,
    )
    submission = state.record_submission(
        Submission(
            id=new_id(),
            source_message_key=f"integration-submission-{run_id}",
            game_id=game.id,
            player_id=player.id,
            body_text="A",
            received_at=now,
            is_eligible=True,
            created_at=now,
            updated_at=now,
        )
    )
    scored = state.score_game(
        replace(game, scored_at=now, updated_at=now),
        score_events=(
            ScoreEvent(
                id=new_id(),
                idempotency_key=f"integration-score-{run_id}",
                player_id=player.id,
                series_id=series.id,
                event_type=SCORE_EVENT_AUTOMATIC,
                points_delta=1,
                created_at=now,
                game_id=game.id,
                submission_id=submission.id,
            ),
        ),
    )

    assert scored.status == GAME_SCORED
    assert state.read_scoreboard(series_id=series.id)[0].score == 1


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


def test_transaction_rows_places_declarations_before_the_transaction() -> None:
    client = FakeClient([[]])
    adapter = BQAdapter(project_id="project-id", dataset="qotd", client=client)
    fake_bigquery = SimpleNamespace(QueryJobConfig=lambda **kwargs: kwargs)

    with patch("qotd.external.storage.bigquery.importlib.import_module", return_value=fake_bigquery):
        adapter.transaction_rows(
            "DECLARE is_new BOOL DEFAULT TRUE;\nUPDATE games SET status = @status",
            [],
        )

    sql, _ = client.calls[0]
    assert sql.index("DECLARE is_new") < sql.index("BEGIN TRANSACTION;") < sql.index("UPDATE games")


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


def test_create_or_find_player_reads_the_committed_row_when_a_transaction_returns_no_rows() -> None:
    client = FakeClient([[], [{"id": "player-1", "email": "ada@example.com", "nickname": None}]])
    adapter = BQAdapter(project_id="project-id", dataset="qotd", client=client)
    fake_bigquery = SimpleNamespace(QueryJobConfig=lambda **kwargs: kwargs, ScalarQueryParameter=FakeScalarQueryParameter)

    with patch("qotd.external.storage.bigquery.importlib.import_module", return_value=fake_bigquery):
        player = adapter.create_or_find_player(email="ada@example.com")

    assert player.id == "player-1"
    assert "WHERE email = @email" in client.calls[1][0]


def test_parameters_preserve_timestamp_type_for_null_timestamp_fields() -> None:
    adapter = BQAdapter(project_id="project-id", dataset="qotd", client=FakeClient([]))
    fake_bigquery = SimpleNamespace(ScalarQueryParameter=FakeScalarQueryParameter)

    with patch("qotd.external.storage.bigquery.importlib.import_module", return_value=fake_bigquery):
        parameters = adapter._parameters({"sent_at": None, "source_message_key": None})

    assert [(parameter.name, parameter.parameter_type, parameter.value) for parameter in parameters] == [
        ("sent_at", "TIMESTAMP", None),
        ("source_message_key", "STRING", None),
    ]


def test_create_or_find_series_reads_the_committed_row_when_a_transaction_returns_no_rows() -> None:
    client = FakeClient([[], [{"id": "series-1", "name": "2026-08", "starts_on": date(2026, 8, 1), "ends_on": date(2026, 8, 31), "created_at": datetime(2026, 8, 1, tzinfo=UTC), "updated_at": datetime(2026, 8, 1, tzinfo=UTC)}]])
    adapter = BQAdapter(project_id="project-id", dataset="qotd", client=client)
    fake_bigquery = SimpleNamespace(QueryJobConfig=lambda **kwargs: kwargs, ScalarQueryParameter=FakeScalarQueryParameter)

    with patch("qotd.external.storage.bigquery.importlib.import_module", return_value=fake_bigquery):
        series = adapter.create_or_find_series(name="2026-08", starts_on=date(2026, 8, 1), ends_on=date(2026, 8, 31))

    assert series.id == "series-1"
    assert "WHERE name = @name" in client.calls[1][0]


def test_reconcile_outbound_message_reads_the_reconciled_message_after_commit() -> None:
    sent_at = datetime(2026, 8, 10, tzinfo=UTC)
    row = {
        "id": "outbound-1", "idempotency_key": "outcome:message", "message_type": "organizer_instruction_outcome",
        "recipient": "organizer@example.com", "subject": "Result", "body_text": "Done", "status": OUTBOUND_SENT,
        "created_at": sent_at, "game_id": None, "organizer_instruction_id": None,
        "source_message_key": "gmail:message", "sent_at": sent_at,
    }
    client = FakeClient([[], [row]])
    adapter = BQAdapter(project_id="project-id", dataset="qotd", client=client)
    fake_bigquery = SimpleNamespace(QueryJobConfig=lambda **kwargs: kwargs, ScalarQueryParameter=FakeScalarQueryParameter)

    with patch("qotd.external.storage.bigquery.importlib.import_module", return_value=fake_bigquery):
        reconciled = adapter.reconcile_outbound_message(
            idempotency_key="outcome:message", source_message_key="gmail:message", sent_at=sent_at
        )

    assert reconciled.status == OUTBOUND_SENT
    assert len(client.calls) == 2
    assert "UPDATE `project-id.qotd.outbound_messages`" in client.calls[0][0]
    assert "SELECT * FROM `project-id.qotd.outbound_messages`" in client.calls[1][0]


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
    assert "prior.source_message_key < selected_submission.source_message_key" in sql
    assert "later.source_message_key > selected_submission.source_message_key" in sql


def test_record_answer_instruction_parses_question_options_as_json() -> None:
    client = FakeClient([[], []])
    adapter = BQAdapter(project_id="project-id", dataset="qotd", client=client)
    fake_bigquery = SimpleNamespace(QueryJobConfig=lambda **kwargs: kwargs, ScalarQueryParameter=FakeScalarQueryParameter)
    now = datetime(2026, 8, 11, tzinfo=UTC)
    instruction = OrganizerInstruction("instruction-1", "message-1", "organizer@example.com", "Answer", now, "set-answer", "applied", now)
    series = Series("series-1", "2026-08", date(2026, 8, 1), date(2026, 8, 31), now, now)
    game = Game(
        "game-1", series.id, date(2026, 8, 10), GAME_PUBLISHED, PUBLICATION_AUTOMATED, now,
        now, now, question_options={"A": "One"}, correct_option="A",
    )

    with patch("qotd.external.storage.bigquery.importlib.import_module", return_value=fake_bigquery):
        adapter.record_answer_instruction(instruction=instruction, series=series, game=game)

    assert "PARSE_JSON(@game_question_options) AS question_options" in client.calls[0][0]


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


def test_automated_publication_transaction_persists_a_published_game() -> None:
    """Automated delivery is a publication transition, never a pending Game."""

    now = datetime(2026, 8, 10, tzinfo=UTC)
    game = Game(
        "game-1", "series-1", date(2026, 8, 10), GAME_PENDING, "automated", now, now, now,
        correct_option="A",
    )
    outbound = OutboundMessage(
        "outbound-1", "publication:2026-08-10", "question_publication", "group@example.com",
        "QOTD", "Question", OUTBOUND_PENDING, now,
    )
    client = FakeClient([[]])
    adapter = BQAdapter(project_id="project-id", dataset="qotd", client=client)
    fake_bigquery = SimpleNamespace(
        QueryJobConfig=lambda **kwargs: kwargs,
        ScalarQueryParameter=FakeScalarQueryParameter,
    )

    with patch("qotd.external.storage.bigquery.importlib.import_module", return_value=fake_bigquery):
        published = adapter.replace_pending_game(game, outbound_message=outbound)

    sql, config = client.calls[0]
    assert isinstance(config, dict)
    assert published.status == GAME_PUBLISHED
    assert "INSERT INTO `project-id.qotd.games`" in sql
    assert "FROM (SELECT 1)\n                WHERE NOT EXISTS" in sql
    assert any(
        parameter.name == "status" and parameter.value == GAME_PUBLISHED
        for parameter in config["query_parameters"]
    )


def test_publication_transition_merges_series_with_its_game_in_one_bq_script() -> None:
    """A publication cannot leave a prerequisite Series committed by itself."""

    source = inspect.getsource(BQAdapter.replace_pending_game)
    assert "self.table('series')" in source
    assert source.index("self.table('series')") < source.index('self.table("games")')

    from qotd.usecases import publish_game

    assert "create_or_find_series" not in inspect.getsource(publish_game._publication_game)


def test_manual_score_event_transition_merges_player_with_instruction_event_and_outbound() -> None:
    """A Manual Score Event cannot leave a prerequisite Player committed by itself."""

    source = inspect.getsource(BQAdapter.record_manual_score_event_instruction)
    assert source.count("MERGE `") >= 3
    assert "self.table('players')" in source
    assert "self.table('organizer_instructions')" in source
    assert "self.table('score_events')" in source
    assert "self.table('outbound_messages')" in source

    from qotd.usecases import record_score_event

    assert "create_or_find_player" not in inspect.getsource(record_score_event.record_score_event)


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
