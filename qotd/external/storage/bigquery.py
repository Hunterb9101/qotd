"""BigQuery-backed state adapter for QOTD workflows."""

from __future__ import annotations

import importlib
import json
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

from qotd.external.auth.gcp import build_oauth_credentials
from qotd.domain.canonical import (
    Game,
    INSTRUCTION_DUPLICATE,
    OrganizerInstruction,
    OutboundMessage,
    Player,
    ScoreEvent,
    ScoreboardEntry,
    Series,
    Submission,
    new_id,
)
from qotd.external.storage.core import StorageClient
from qotd.external.storage.canonical import CanonicalState
from qotd.domain.models import CorrectAnswerUpdate, ManualAdjustment, MonthlyScore, ReplyProcessingRecord, StoredQuestion


BIGQUERY_SCOPE = "https://www.googleapis.com/auth/bigquery"
MAX_TRANSACTION_ATTEMPTS = 3


class BQAdapter(StorageClient, CanonicalState):
    """BigQuery-backed QOTD state store during the canonical cutover."""

    def __init__(self, *, project_id: str, dataset: str, client: Any) -> None:
        self.project_id = project_id
        self.dataset = dataset
        self.client = client

    @classmethod
    def from_oauth(
        cls,
        *,
        project_id: str,
        dataset: str,
        oauth_client_id: str,
        oauth_client_secret: str,
        oauth_refresh_token: str,
    ) -> BQAdapter:
        """Build a BigQuery state adapter from OAuth user credentials."""

        bigquery = importlib.import_module("google.cloud.bigquery")
        credentials = build_oauth_credentials(
            client_id=oauth_client_id,
            client_secret=oauth_client_secret,
            refresh_token=oauth_refresh_token,
            scopes=[BIGQUERY_SCOPE],
        )
        return cls(
            project_id=project_id,
            dataset=dataset,
            client=bigquery.Client(project=project_id, credentials=credentials),
        )

    def table(self, name: str) -> str:
        """Return a fully qualified table id."""

        return f"{self.project_id}.{self.dataset}.{name}"

    def insert_rows(self, table_name: str, rows: list[dict[str, Any]]) -> None:
        """Append rows with a load job and raise if BigQuery rejects them."""

        bigquery = importlib.import_module("google.cloud.bigquery")
        job = self.client.load_table_from_json(
            rows,
            self.table(table_name),
            job_config=bigquery.LoadJobConfig(write_disposition=bigquery.WriteDisposition.WRITE_APPEND),
        )
        job.result()
        if job.errors:
            raise RuntimeError(f"BigQuery load failed for {table_name}: {job.errors}")

    def query_rows(self, query: str, parameters: list[Any] | None = None) -> list[dict[str, Any]]:
        """Run a parameterized query and return dict rows."""

        bigquery = importlib.import_module("google.cloud.bigquery")
        job_config = bigquery.QueryJobConfig(query_parameters=parameters or [])
        return [dict(row.items()) for row in self.client.query(query, job_config=job_config).result()]

    def transaction_rows(self, statement: str, parameters: list[Any]) -> list[dict[str, Any]]:
        """Run parameterized GoogleSQL DML in a bounded-retry transaction."""

        bigquery = importlib.import_module("google.cloud.bigquery")
        script = f"BEGIN TRANSACTION;\n{statement}\nCOMMIT TRANSACTION;"
        job_config = bigquery.QueryJobConfig(query_parameters=parameters)
        for attempt in range(MAX_TRANSACTION_ATTEMPTS):
            try:
                return [dict(row.items()) for row in self.client.query(script, job_config=job_config).result()]
            except Exception as exc:
                if not self._is_transaction_conflict(exc) or attempt == MAX_TRANSACTION_ATTEMPTS - 1:
                    raise RuntimeError("BigQuery canonical-state transaction failed") from exc
        raise AssertionError("unreachable")

    @staticmethod
    def _is_transaction_conflict(error: Exception) -> bool:
        """Identify BigQuery's retryable concurrent-transaction failures."""

        message = str(error).lower()
        return "concurrent update" in message or "transaction" in message and "cancel" in message

    def _parameters(self, values: dict[str, Any]) -> list[Any]:
        """Build typed BigQuery parameters without interpolating input values."""

        bigquery = importlib.import_module("google.cloud.bigquery")
        parameters: list[Any] = []
        for name, value in values.items():
            if isinstance(value, dict):
                value = json.dumps(value)
                parameter_type = "STRING"
            elif isinstance(value, bool):
                parameter_type = "BOOL"
            elif isinstance(value, int):
                parameter_type = "INT64"
            elif hasattr(value, "isoformat") and value.__class__.__name__ == "date":
                parameter_type = "DATE"
            elif isinstance(value, datetime):
                parameter_type = "TIMESTAMP"
            else:
                parameter_type = "STRING"
            parameters.append(bigquery.ScalarQueryParameter(name, parameter_type, value))
        return parameters

    def _merge_record(self, *, table_name: str, key: str, values: dict[str, Any]) -> list[dict[str, Any]]:
        """Idempotently insert one canonical record and return its stored row."""

        fields = tuple(values)
        field_list = ", ".join(fields)
        source_fields = ", ".join(
            f"PARSE_JSON(@{field}) AS {field}" if isinstance(values[field], dict) else f"@{field} AS {field}"
            for field in fields
        )
        value_list = ", ".join(f"source.{field}" for field in fields)
        statement = f"""
            MERGE `{self.table(table_name)}` AS target
            USING (SELECT {source_fields}) AS source
            ON target.{key} = source.{key}
            WHEN NOT MATCHED THEN
              INSERT ({field_list}) VALUES ({value_list});
            SELECT {field_list} FROM `{self.table(table_name)}` WHERE {key} = @{key};
        """
        return self.transaction_rows(statement, self._parameters(values))

    def create_or_find_player(self, *, email: str) -> Player:
        """Create or look up a Player by normalized email."""

        normalized = email.strip().lower()
        rows = self._merge_record(
            table_name="players", key="email", values={"id": new_id(), "email": normalized, "nickname": None}
        )
        row = rows[0]
        return Player(id=str(row["id"]), email=str(row["email"]), nickname=row.get("nickname"))

    def create_or_find_series(self, *, name: str, starts_on: Any, ends_on: Any) -> Series:
        """Create or look up a Series by name."""

        now = datetime.now(UTC)
        rows = self._merge_record(
            table_name="series", key="name",
            values={"id": new_id(), "name": name, "starts_on": starts_on, "ends_on": ends_on,
                    "created_at": now, "updated_at": now},
        )
        row = rows[0]
        return Series(**row)

    def record_organizer_instruction(self, instruction: OrganizerInstruction) -> OrganizerInstruction:
        rows = self._merge_record(
            table_name="organizer_instructions", key="source_message_key", values=asdict(instruction)
        )
        if rows and str(rows[0]["id"]) != instruction.id:
            return OrganizerInstruction(**{**rows[0], "status": INSTRUCTION_DUPLICATE})
        return OrganizerInstruction(**rows[0]) if rows else instruction

    def find_organizer_instruction(self, *, source_message_key: str) -> OrganizerInstruction | None:
        rows = self.query_rows(
            f"SELECT * FROM `{self.table('organizer_instructions')}` WHERE source_message_key = @source_message_key",
            self._parameters({"source_message_key": source_message_key}),
        )
        return OrganizerInstruction(**rows[0]) if rows else None

    def record_submission(self, submission: Submission) -> Submission:
        values = asdict(submission)
        fields = tuple(values)
        statement = f"""
            MERGE `{self.table('submissions')}` AS target
            USING (SELECT {', '.join(f'@{field} AS {field}' for field in fields)}) AS source
            ON target.source_message_key = source.source_message_key
            WHEN NOT MATCHED THEN INSERT ({', '.join(fields)}) VALUES ({', '.join(f'source.{field}' for field in fields)});
            UPDATE `{self.table('submissions')}` AS item
            SET is_eligible = item.received_at < game.deadline_at,
                ineligibility_reason = IF(item.received_at < game.deadline_at, NULL, 'late')
            FROM `{self.table('games')}` AS game
            WHERE item.source_message_key = @source_message_key AND item.game_id = game.id;
            UPDATE `{self.table('submissions')}` AS prior
            SET is_eligible = FALSE, ineligibility_reason = 'superseded', updated_at = @updated_at
            FROM `{self.table('submissions')}` AS current
            WHERE current.source_message_key = @source_message_key
              AND current.is_eligible
              AND prior.game_id = current.game_id AND prior.player_id = current.player_id
              AND prior.is_eligible
              AND (
                prior.received_at < current.received_at
                OR (prior.received_at = current.received_at AND prior.source_message_key < current.source_message_key)
              );
            UPDATE `{self.table('submissions')}` AS current
            SET is_eligible = FALSE, ineligibility_reason = 'superseded', updated_at = @updated_at
            WHERE current.source_message_key = @source_message_key
              AND current.is_eligible
              AND EXISTS (
                SELECT 1 FROM `{self.table('submissions')}` AS later
                WHERE later.game_id = current.game_id AND later.player_id = current.player_id
                  AND later.is_eligible
                  AND (
                    later.received_at > current.received_at
                    OR (later.received_at = current.received_at AND later.source_message_key > current.source_message_key)
                  )
              );
            SELECT * FROM `{self.table('submissions')}` WHERE source_message_key = @source_message_key;
        """
        rows = self.transaction_rows(statement, self._parameters(values))
        return Submission(**rows[0]) if rows else submission

    def find_game(self, *, day: Any) -> Game | None:
        """Return the Game for a Day, if one has been published or is pending."""

        rows = self.query_rows(
            f"SELECT * FROM `{self.table('games')}` WHERE day = @day LIMIT 1",
            self._parameters({"day": day}),
        )
        return Game(**rows[0]) if rows else None

    def find_latest_answered_game_before(self, *, day: Any) -> Game | None:
        rows = self.query_rows(
            f"""SELECT * FROM `{self.table('games')}`
            WHERE day < @day AND correct_option IS NOT NULL
            ORDER BY day DESC LIMIT 1""",
            self._parameters({"day": day}),
        )
        return Game(**rows[0]) if rows else None

    def find_games_between(self, *, starts_on: Any, ends_on: Any) -> tuple[Game, ...]:
        rows = self.query_rows(
            f"""SELECT * FROM `{self.table('games')}`
            WHERE day BETWEEN @starts_on AND @ends_on ORDER BY day""",
            self._parameters({"starts_on": starts_on, "ends_on": ends_on}),
        )
        return tuple(Game(**row) for row in rows)

    def publish_game(self, game: Game, *, outbound_message: OutboundMessage | None = None) -> Game:
        values = asdict(game)
        fields = tuple(values)
        source_fields = ", ".join(
            f"PARSE_JSON(@{field}) AS {field}" if isinstance(values[field], dict) else f"@{field} AS {field}"
            for field in fields
        )
        insert_values = ", ".join(f"source.{field}" for field in fields)
        updates = ", ".join(
            "target.status = 'published'"
            if field == "status"
            else f"target.{field} = COALESCE(target.{field}, source.{field})"
            if field in {"correct_option", "answer_source_url", "answer_source_note", "answer_instruction_id"}
            else f"target.{field} = source.{field}"
            for field in fields
            if field not in {"id", "series_id", "day", "created_at"}
        )
        statement = f"""
            MERGE `{self.table("games")}` AS target
            USING (SELECT {source_fields}) AS source
            ON target.day = source.day
            WHEN NOT MATCHED THEN INSERT ({", ".join(fields)}) VALUES ({insert_values})
            WHEN MATCHED AND target.status = 'pending' THEN UPDATE SET {updates};
        """
        if outbound_message is not None:
            outbound = {f"outbound_{key}": value for key, value in asdict(outbound_message).items()}
            outbound_fields = tuple(asdict(outbound_message))
            statement += f"""
                INSERT INTO `{self.table('outbound_messages')}` ({", ".join(outbound_fields)})
                SELECT {", ".join(f"@outbound_{field}" for field in outbound_fields)}
                WHERE NOT EXISTS (SELECT 1 FROM `{self.table('outbound_messages')}` WHERE idempotency_key = @outbound_idempotency_key);
            """
            values.update(outbound)
        statement += f"SELECT * FROM `{self.table('games')}` WHERE day = @day;"
        return self._game_from_rows(self.transaction_rows(statement, self._parameters(values)), fallback=game)

    def set_answer(self, game: Game) -> Game:
        values = asdict(game)
        fields = tuple(values)
        source_fields = ", ".join(
            f"PARSE_JSON(@{field}) AS {field}" if isinstance(values[field], dict) else f"@{field} AS {field}"
            for field in fields
        )
        insert_values = ", ".join(f"source.{field}" for field in fields)
        statement = f"""
            MERGE `{self.table("games")}` AS target
            USING (SELECT {source_fields}) AS source
            ON target.day = source.day
            WHEN NOT MATCHED THEN INSERT ({", ".join(fields)}) VALUES ({insert_values})
            WHEN MATCHED AND target.correct_option IS NULL THEN UPDATE SET
              correct_option = source.correct_option,
              answer_source_url = source.answer_source_url,
              answer_source_note = source.answer_source_note,
              answer_instruction_id = source.answer_instruction_id,
              updated_at = source.updated_at;
            ASSERT EXISTS (
              SELECT 1 FROM `{self.table("games")}` WHERE day = @day AND correct_option = @correct_option
            ) AS 'Game Answer is missing or conflicts with the existing Answer';
        """
        rows = self.transaction_rows(
            statement + f"SELECT * FROM `{self.table('games')}` WHERE day = @day;", self._parameters(values)
        )
        return self._game_from_rows(rows, fallback=game)

    def discard_pending_game(self, *, day: Any) -> None:
        statement = f"DELETE FROM `{self.table('games')}` WHERE day = @day AND status = 'pending';"
        self.transaction_rows(statement, self._parameters({"day": day}))

    def replace_pending_game(self, game: Game, *, outbound_message: OutboundMessage | None = None) -> Game:
        values = asdict(game)
        fields = ", ".join(values)
        source_fields = ", ".join(
            f"PARSE_JSON(@{field}) AS {field}" if isinstance(values[field], dict) else f"@{field} AS {field}"
            for field in values
        )
        statement = f"""
            DELETE FROM `{self.table('games')}` WHERE day = @day AND status = 'pending';
            INSERT INTO `{self.table('games')}` ({fields}) SELECT {", ".join(f"source.{field}" for field in values)}
            FROM (SELECT {source_fields}) AS source
            WHERE NOT EXISTS (SELECT 1 FROM `{self.table('games')}` WHERE day = @day);
        """
        if outbound_message is not None:
            outbound = {f"outbound_{key}": value for key, value in asdict(outbound_message).items()}
            outbound_fields = tuple(asdict(outbound_message))
            statement += f"""
                INSERT INTO `{self.table('outbound_messages')}` ({", ".join(outbound_fields)})
                SELECT {", ".join(f"@outbound_{field}" for field in outbound_fields)}
                WHERE NOT EXISTS (SELECT 1 FROM `{self.table('outbound_messages')}` WHERE idempotency_key = @outbound_idempotency_key);
            """
            values.update(outbound)
        statement += f"SELECT * FROM `{self.table('games')}` WHERE day = @day;"
        return self._game_from_rows(self.transaction_rows(statement, self._parameters(values)), fallback=game)

    def score_game(
        self,
        game: Game,
        *,
        score_events: tuple[ScoreEvent, ...] = (),
        outbound_messages: tuple[OutboundMessage, ...] = (),
    ) -> Game:
        statements = ["""
            DECLARE transitioned BOOL DEFAULT FALSE;
            DECLARE events_valid BOOL DEFAULT TRUE;
        """]
        parameters = asdict(game)
        for index, event in enumerate(score_events):
            event_values = {f"event_{index}_{key}": value for key, value in asdict(event).items()}
            statements.append(
                f"""SET events_valid = events_valid AND EXISTS (
                    SELECT 1 FROM `{self.table("submissions")}`
                    WHERE id = @event_{index}_submission_id
                      AND game_id = @id
                      AND player_id = @event_{index}_player_id
                      AND is_eligible
                      AND ineligibility_reason IS NULL
                )
                AND @event_{index}_game_id = @id
                AND @event_{index}_event_type = 'automatic'
                AND @event_{index}_series_id = (
                    SELECT series_id FROM `{self.table("games")}` WHERE id = @id
                );"""
            )
            parameters.update(event_values)
        statements.append(f"""
            UPDATE `{self.table("games")}`
            SET status = 'scored', scored_at = @scored_at, updated_at = @updated_at
            WHERE id = @id AND status = 'published' AND correct_option IS NOT NULL AND events_valid;
            SET transitioned = @@row_count = 1;
            ASSERT transitioned OR EXISTS (
              SELECT 1 FROM `{self.table("games")}` WHERE id = @id AND status = 'scored'
            ) AS 'Game cannot be scored before publication and an Answer';
        """)
        for index, event in enumerate(score_events):
            fields = tuple(asdict(event))
            statements.append(
                f"""INSERT INTO `{self.table("score_events")}` ({", ".join(fields)})
                SELECT {", ".join(f"@event_{index}_{field}" for field in fields)} WHERE transitioned;"""
            )
        for index, message in enumerate(outbound_messages):
            message_values = {f"outbound_{index}_{key}": value for key, value in asdict(message).items()}
            fields = tuple(asdict(message))
            statements.append(
                f"""INSERT INTO `{self.table("outbound_messages")}` ({", ".join(fields)})
                SELECT {", ".join(f"@outbound_{index}_{field}" for field in fields)} WHERE transitioned;"""
            )
            parameters.update(message_values)
        statements.append(f"SELECT * FROM `{self.table('games')}` WHERE id = @id;")
        return self._game_from_rows(
            self.transaction_rows("\n".join(statements), self._parameters(parameters)), fallback=game
        )

    @staticmethod
    def _game_from_rows(rows: list[dict[str, Any]], *, fallback: Game) -> Game:
        """Return the database Game state, with a test-double fallback."""

        return Game(**rows[0]) if rows else fallback

    def record_manual_score_event(self, event: ScoreEvent) -> ScoreEvent:
        self._merge_record(table_name="score_events", key="idempotency_key", values=asdict(event))
        return event

    def record_instruction_score_event(self, *, instruction: OrganizerInstruction, event: ScoreEvent) -> ScoreEvent:
        instruction_values = {f"instruction_{key}": value for key, value in asdict(instruction).items()}
        event_values = {f"event_{key}": value for key, value in asdict(event).items()}
        statement = f"""
            DECLARE instruction_is_new BOOL DEFAULT NOT EXISTS (
                SELECT 1 FROM `{self.table('organizer_instructions')}`
                WHERE source_message_key = @instruction_source_message_key
            );
            MERGE `{self.table('organizer_instructions')}` AS target
            USING (SELECT {', '.join(f'@instruction_{field} AS {field}' for field in asdict(instruction))}) AS source
            ON target.source_message_key = source.source_message_key
            WHEN NOT MATCHED THEN INSERT ({', '.join(asdict(instruction))}) VALUES ({', '.join(f'source.{field}' for field in asdict(instruction))});
            INSERT INTO `{self.table('score_events')}` ({', '.join(asdict(event))})
            SELECT {', '.join(f'@event_{field}' for field in asdict(event))}
            WHERE instruction_is_new
              AND NOT EXISTS (SELECT 1 FROM `{self.table('score_events')}` WHERE idempotency_key = @event_idempotency_key);
            SELECT * FROM `{self.table('score_events')}` WHERE idempotency_key = @event_idempotency_key;
        """
        rows = self.transaction_rows(statement, self._parameters({**instruction_values, **event_values}))
        return ScoreEvent(**rows[0]) if rows else event

    def record_outbound_message(self, message: OutboundMessage) -> OutboundMessage:
        self._merge_record(table_name="outbound_messages", key="idempotency_key", values=asdict(message))
        return message

    def reconcile_outbound_message(
        self, *, idempotency_key: str, source_message_key: str, sent_at: datetime
    ) -> OutboundMessage:
        statement = f"""
            UPDATE `{self.table("outbound_messages")}`
            SET status = 'sent', source_message_key = @source_message_key, sent_at = @sent_at
            WHERE idempotency_key = @idempotency_key AND status = 'pending';
            SELECT * FROM `{self.table("outbound_messages")}` WHERE idempotency_key = @idempotency_key;
        """
        rows = self.transaction_rows(
            statement,
            self._parameters({"idempotency_key": idempotency_key, "source_message_key": source_message_key, "sent_at": sent_at}),
        )
        return OutboundMessage(**rows[0])

    def read_scoreboard(self, *, series_id: str) -> tuple[ScoreboardEntry, ...]:
        rows = self.query_rows(
            f"SELECT series_id, player_id, email, score FROM `{self.table('scoreboard')}` WHERE series_id = @series_id",
            self._parameters({"series_id": series_id}),
        )
        return tuple(ScoreboardEntry(**row) for row in rows)

    def append_question_record(self, record: StoredQuestion) -> None:
        """Append one question record."""

        self.insert_rows(
            "questions",
            [
                {
                    "game_date": record.game_date,
                    "prompt": record.prompt,
                    "options": record.options,
                    "correct_option": record.correct_option,
                    "source_note": record.source_note,
                    "source_url": record.source_url,
                    "source": record.source,
                    "gmail_message_id": record.gmail_message_id,
                    "created_at": record.created_at,
                }
            ],
        )

    def read_question_records(self) -> list[dict[str, Any]]:
        """Read question records."""

        records = self.query_rows(
            f"""
            SELECT
              CAST(game_date AS STRING) AS game_date,
              prompt,
              TO_JSON_STRING(options) AS options,
              correct_option,
              source_note,
              source_url,
              source,
              gmail_message_id,
              CAST(created_at AS STRING) AS created_at
            FROM `{self.table("questions")}`
            ORDER BY created_at
            """
        )
        for record in records:
            options = record.get("options")
            if isinstance(options, str):
                record["options"] = json.loads(options)
        return records

    def append_monthly_score(self, record: MonthlyScore) -> None:
        """Append one monthly score record."""

        self.insert_rows(
            "monthly_scores",
            [
                {
                    "series": record.series,
                    "email": record.email,
                    "points": record.points,
                    "updated_at": datetime.now(UTC).isoformat(),
                }
            ],
        )

    def read_monthly_scores(self, *, series: str | None = None) -> list[dict[str, Any]]:
        """Read monthly score records."""

        parameters = []
        where_clause = ""
        if series is not None:
            bigquery = importlib.import_module("google.cloud.bigquery")
            where_clause = "WHERE series = @series"
            parameters.append(bigquery.ScalarQueryParameter("series", "STRING", series))
        return self.query_rows(
            f"""
            SELECT series, email, points
            FROM `{self.table("monthly_scores")}`
            {where_clause}
            ORDER BY updated_at
            """,
            parameters,
        )

    def append_reply_processing_record(
        self,
        record: ReplyProcessingRecord,
        *,
        interpreted_option: str | None = None,
    ) -> None:
        """Append one reply-processing record."""

        self.insert_rows(
            "reply_processing",
            [
                {
                    "game_date": record.game_date,
                    "email": record.email,
                    "processing_key": record.processing_key,
                    "latest_gmail_message_id": record.latest_gmail_message_id,
                    "interpreted_option": interpreted_option,
                    "points_awarded": record.points_awarded,
                    "needs_audit": record.needs_audit,
                    "processed_at": record.processed_at,
                }
            ],
        )

    def read_reply_processing_records(self, *, game_date: str | None = None) -> list[dict[str, Any]]:
        """Read reply-processing records."""

        parameters = []
        where_clause = ""
        if game_date is not None:
            bigquery = importlib.import_module("google.cloud.bigquery")
            where_clause = "WHERE game_date = @game_date"
            parameters.append(bigquery.ScalarQueryParameter("game_date", "DATE", game_date))
        return self.query_rows(
            f"""
            SELECT
              CAST(game_date AS STRING) AS game_date,
              email,
              processing_key,
              latest_gmail_message_id,
              interpreted_option,
              points_awarded,
              needs_audit,
              CAST(processed_at AS STRING) AS processed_at
            FROM `{self.table("reply_processing")}`
            {where_clause}
            ORDER BY processed_at
            """,
            parameters,
        )

    def append_manual_adjustment(self, record: ManualAdjustment) -> None:
        """Append one manual adjustment record."""

        self.insert_rows("manual_adjustments", [record.to_json_dict()])

    def read_manual_adjustments(self) -> list[dict[str, Any]]:
        """Read manual adjustment records."""

        return self.query_rows(f"SELECT * FROM `{self.table('manual_adjustments')}` ORDER BY created_at")

    def append_correct_answer_update(self, record: CorrectAnswerUpdate) -> None:
        """Append one correct-answer update record."""

        self.insert_rows("correct_answer_updates", [record.to_json_dict()])

    def read_correct_answer_updates(self, *, game_date: str | None = None) -> list[dict[str, Any]]:
        """Read correct-answer update records."""

        parameters = []
        where_clause = ""
        if game_date is not None:
            bigquery = importlib.import_module("google.cloud.bigquery")
            where_clause = "WHERE game_date = @game_date"
            parameters.append(bigquery.ScalarQueryParameter("game_date", "DATE", game_date))
        return self.query_rows(
            f"SELECT * FROM `{self.table('correct_answer_updates')}` {where_clause} ORDER BY created_at",
            parameters,
        )


def build_bigquery_state_store(
    *,
    project_id: str,
    dataset: str,
    oauth_client_id: str,
    oauth_client_secret: str,
    oauth_refresh_token: str,
) -> BQAdapter:
    """Build the production BigQuery state store."""

    if not project_id:
        raise ValueError("Google Cloud project is required")
    if not dataset:
        raise ValueError("BigQuery dataset is required")
    return BQAdapter.from_oauth(
        project_id=project_id,
        dataset=dataset,
        oauth_client_id=oauth_client_id,
        oauth_client_secret=oauth_client_secret,
        oauth_refresh_token=oauth_refresh_token,
    )
