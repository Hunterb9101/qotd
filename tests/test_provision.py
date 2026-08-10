from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from qotd.provision import provision_canonical_state, validate_target


SQL_DIRECTORY = Path(__file__).parent.parent / "sql"
SQL = (SQL_DIRECTORY / "001_canonical_state.sql").read_text().lower()
RESET_SQL_PATH = SQL_DIRECTORY / "002_reset_legacy_state.sql"
RESET_SQL = RESET_SQL_PATH.read_text().lower() if RESET_SQL_PATH.exists() else None

TABLE_FIELDS = {
    "series": {"id", "name", "starts_on", "ends_on", "created_at", "updated_at"},
    "players": {"id", "email", "nickname"},
    "games": {
        "id", "series_id", "day", "status", "publication_mode", "question_prompt",
        "question_options", "publication_subject", "published_at", "publication_message_key",
        "publication_instruction_id", "deadline_at", "correct_option", "answer_source_url",
        "answer_source_note", "answer_instruction_id", "scored_at", "created_at", "updated_at",
    },
    "organizer_instructions": {
        "id", "source_message_key", "sender_email", "subject", "received_at", "action",
        "status", "rejection_reason", "processed_at",
    },
    "submissions": {
        "id", "source_message_key", "game_id", "player_id", "body_text", "received_at",
        "interpreted_option", "is_eligible", "ineligibility_reason", "created_at", "updated_at",
    },
    "score_events": {
        "id", "idempotency_key", "player_id", "series_id", "game_id", "submission_id",
        "organizer_instruction_id", "event_type", "points_delta", "reason", "created_at",
    },
    "outbound_messages": {
        "id", "idempotency_key", "message_type", "game_id", "organizer_instruction_id",
        "recipient", "subject", "body_text", "status", "source_message_key", "created_at", "sent_at",
    },
}


def table_definition(table: str) -> str:
    start = SQL.index(f"create table if not exists {table} (")
    return SQL[start : SQL.index(");", start)]


def test_canonical_tables_have_all_adr_004_fields() -> None:
    for table, fields in TABLE_FIELDS.items():
        definition = table_definition(table)
        for field in fields:
            assert f"\n  {field} " in definition


def test_canonical_schema_declares_logical_key_fields() -> None:
    assert "email string not null" in table_definition("players")
    assert "day date not null" in table_definition("games")
    assert "source_message_key string not null" in table_definition("organizer_instructions")
    assert "source_message_key string not null" in table_definition("submissions")
    assert "idempotency_key string not null" in table_definition("score_events")


def test_scoreboard_is_a_view_derived_from_submissions_and_score_events() -> None:
    assert "create or replace view scoreboard" in SQL
    assert "from submissions" in SQL
    assert "left join score_events" in SQL
    assert "coalesce(sum(score_events.points_delta), 0) as score" in SQL


@pytest.mark.skipif(
    RESET_SQL is None,
    reason="legacy reset SQL is intentionally unavailable",
)
def test_reset_script_drops_only_the_named_legacy_tables() -> None:
    assert RESET_SQL is not None
    legacy_tables = {
        "correct_answer_updates", "manual_adjustments", "monthly_scores", "questions", "reply_processing",
    }
    statements = [
        line.strip().removeprefix("drop table if exists ").removesuffix(";")
        for line in RESET_SQL.splitlines()
        if line.startswith("drop table")
    ]
    assert set(statements) == legacy_tables
    assert "drop schema" not in RESET_SQL
    for table, fields in TABLE_FIELDS.items():
        start = RESET_SQL.index(f"create table if not exists {table} (")
        definition = RESET_SQL[start : RESET_SQL.index(");", start)]
        for field in fields:
            assert f"\n  {field} " in definition
    assert "create or replace view scoreboard" in RESET_SQL


class FakeJob:
    def result(self) -> None:
        return None


class FakeClient:
    def __init__(self) -> None:
        self.dataset = SimpleNamespace(
            project="valid-project",
            dataset_id="qotd",
            reference="valid-project.qotd",
        )
        self.queries: list[tuple[str, dict[str, Any]]] = []

    def get_dataset(self, target: str) -> object:
        assert target == "valid-project.qotd"
        return self.dataset

    def query(self, sql: str, *, job_config: dict[str, Any]) -> FakeJob:
        self.queries.append((sql, job_config))
        return FakeJob()


def test_validate_target_rejects_invalid_identifiers() -> None:
    with pytest.raises(ValueError, match="project"):
        validate_target(project_id="not a project", dataset="qotd")
    with pytest.raises(ValueError, match="dataset"):
        validate_target(project_id="valid-project", dataset="bad-dataset")


def test_provision_validates_the_existing_target_then_applies_schema() -> None:
    client = FakeClient()
    fake_bigquery = SimpleNamespace(QueryJobConfig=lambda **kwargs: kwargs)

    with patch("qotd.provision.importlib.import_module", return_value=fake_bigquery):
        provision_canonical_state(client=client, project_id="valid-project", dataset="qotd")

    assert len(client.queries) == 1
    assert "create table if not exists series" in client.queries[0][0].lower()
    assert client.queries[0][1]["default_dataset"] == "valid-project.qotd"


@pytest.mark.skipif(
    RESET_SQL is None,
    reason="legacy reset SQL is intentionally unavailable",
)
def test_reset_applies_a_standalone_scoped_reset_and_canonical_schema() -> None:
    client = FakeClient()
    fake_bigquery = SimpleNamespace(QueryJobConfig=lambda **kwargs: kwargs)

    with patch("qotd.provision.importlib.import_module", return_value=fake_bigquery):
        provision_canonical_state(
            client=client,
            project_id="valid-project",
            dataset="qotd",
            reset_legacy_state=True,
        )

    assert len(client.queries) == 1
    assert "drop table if exists monthly_scores" in client.queries[0][0].lower()
    assert "create table if not exists series" in client.queries[0][0].lower()
