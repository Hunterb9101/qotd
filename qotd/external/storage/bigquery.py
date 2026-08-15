"""BigQuery-backed state adapter for QOTD workflows."""

from __future__ import annotations

import importlib
import json
from dataclasses import asdict, replace
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
from qotd.external.storage.canonical import CanonicalState


BIGQUERY_SCOPE = "https://www.googleapis.com/auth/bigquery"
MAX_TRANSACTION_ATTEMPTS = 3


class BQAdapter(CanonicalState):
    """BigQuery-backed canonical QOTD state store."""

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

    def query_rows(self, query: str, parameters: list[Any] | None = None) -> list[dict[str, Any]]:
        """Run a parameterized query and return dict rows."""

        bigquery = importlib.import_module("google.cloud.bigquery")
        job_config = bigquery.QueryJobConfig(query_parameters=parameters or [])
        return [dict(row.items()) for row in self.client.query(query, job_config=job_config).result()]

    def transaction_rows(self, statement: str, parameters: list[Any]) -> list[dict[str, Any]]:
        """Run parameterized GoogleSQL DML in a bounded-retry transaction."""

        bigquery = importlib.import_module("google.cloud.bigquery")
        declarations, transactional_statement = self._split_leading_declarations(statement)
        script = f"{declarations}BEGIN TRANSACTION;\n{transactional_statement}\nCOMMIT TRANSACTION;"
        job_config = bigquery.QueryJobConfig(query_parameters=parameters)
        for attempt in range(MAX_TRANSACTION_ATTEMPTS):
            try:
                return [dict(row.items()) for row in self.client.query(script, job_config=job_config).result()]
            except Exception as exc:
                if not self._is_transaction_conflict(exc) or attempt == MAX_TRANSACTION_ATTEMPTS - 1:
                    raise RuntimeError("BigQuery canonical-state transaction failed") from exc
        raise AssertionError("unreachable")

    @staticmethod
    def _split_leading_declarations(statement: str) -> tuple[str, str]:
        """Separate leading GoogleSQL DECLARE statements from transactional DML."""

        position = 0
        declarations_end = 0
        length = len(statement)
        while True:
            while position < length and statement[position].isspace():
                position += 1
            if not statement[position:].upper().startswith("DECLARE "):
                break

            parentheses = 0
            while position < length:
                character = statement[position]
                if character == "(":
                    parentheses += 1
                elif character == ")":
                    parentheses -= 1
                elif character == ";" and parentheses == 0:
                    position += 1
                    declarations_end = position
                    break
                position += 1
            else:
                raise ValueError("unterminated GoogleSQL DECLARE statement")

        return statement[:declarations_end], statement[declarations_end:]

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
            elif value is None:
                parameter_type = "TIMESTAMP" if name.endswith("_at") else "STRING"
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
        if not rows:
            rows = self.query_rows(
                f"SELECT * FROM `{self.table('players')}` WHERE email = @email",
                self._parameters({"email": normalized}),
            )
        if not rows:
            raise RuntimeError("Player creation committed without a readable Player row")
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
        if not rows:
            rows = self.query_rows(
                f"SELECT * FROM `{self.table('series')}` WHERE name = @name",
                self._parameters({"name": name}),
            )
        if not rows:
            raise RuntimeError("Series creation committed without a readable Series row")
        row = rows[0]
        return Series(**row)

    def record_organizer_instruction(self, instruction: OrganizerInstruction) -> OrganizerInstruction:
        rows = self._merge_record(
            table_name="organizer_instructions", key="source_message_key", values=asdict(instruction)
        )
        if rows and str(rows[0]["id"]) != instruction.id:
            return OrganizerInstruction(**{**rows[0], "status": INSTRUCTION_DUPLICATE})
        return OrganizerInstruction(**rows[0]) if rows else instruction

    def record_answer_instruction(
        self,
        *,
        instruction: OrganizerInstruction,
        series: Series,
        game: Game,
        outbound_message: OutboundMessage | None = None,
    ) -> tuple[OrganizerInstruction, Game]:
        """Commit an Answer Instruction, its Series, and its Game together."""

        instruction_values = {f"instruction_{key}": value for key, value in asdict(instruction).items()}
        series_values = {f"series_{key}": value for key, value in asdict(series).items()}
        game_values = {f"game_{key}": value for key, value in asdict(game).items()}
        outbound_values = (
            {f"outbound_{key}": value for key, value in asdict(outbound_message).items()}
            if outbound_message is not None else {}
        )
        game_fields = tuple(asdict(game))
        game_source = ", ".join(
            f"(SELECT id FROM `{self.table('series')}` WHERE name = @series_name) AS series_id"
            if field == "series_id"
            else f"PARSE_JSON(@game_{field}) AS {field}"
            if isinstance(game_values[f"game_{field}"], dict)
            else f"@game_{field} AS {field}"
            for field in game_fields
        )
        statement = f"""
            DECLARE instruction_is_new BOOL DEFAULT NOT EXISTS (
                SELECT 1 FROM `{self.table('organizer_instructions')}`
                WHERE source_message_key = @instruction_source_message_key
            );
            MERGE `{self.table('organizer_instructions')}` AS target
            USING (SELECT {', '.join(f'@instruction_{field} AS {field}' for field in asdict(instruction))}) AS source
            ON target.source_message_key = source.source_message_key
            WHEN NOT MATCHED THEN INSERT ({', '.join(asdict(instruction))}) VALUES ({', '.join(f'source.{field}' for field in asdict(instruction))});
            MERGE `{self.table('series')}` AS target
            USING (SELECT {', '.join(f'@series_{field} AS {field}' for field in asdict(series))}) AS source
            ON target.name = source.name
            WHEN NOT MATCHED THEN INSERT ({', '.join(asdict(series))}) VALUES ({', '.join(f'source.{field}' for field in asdict(series))});
            MERGE `{self.table('games')}` AS target
            USING (SELECT {game_source}) AS source
            ON target.day = source.day
            WHEN NOT MATCHED AND instruction_is_new THEN INSERT ({', '.join(game_fields)}) VALUES ({', '.join(f'source.{field}' for field in game_fields)})
            WHEN MATCHED AND instruction_is_new AND target.correct_option IS NULL THEN UPDATE SET
              correct_option = source.correct_option,
              answer_source_url = source.answer_source_url,
              answer_source_note = source.answer_source_note,
              answer_instruction_id = source.answer_instruction_id,
              updated_at = source.updated_at;
            ASSERT NOT instruction_is_new OR EXISTS (
              SELECT 1 FROM `{self.table('games')}`
              WHERE day = @game_day AND correct_option = @game_correct_option
            ) AS 'Game Answer is missing or conflicts with the existing Answer';
            {self._answer_outbound_insert(outbound_message) if outbound_message is not None else ''}
            SELECT * FROM `{self.table('games')}` WHERE day = @game_day;
        """
        rows = self.transaction_rows(
            statement, self._parameters({**instruction_values, **series_values, **game_values, **outbound_values})
        )
        recorded_instruction = self.find_organizer_instruction(
            source_message_key=instruction.source_message_key
        )
        if recorded_instruction is None:
            recorded_instruction = instruction
        elif recorded_instruction.id != instruction.id:
            recorded_instruction = OrganizerInstruction(**{**asdict(recorded_instruction), "status": INSTRUCTION_DUPLICATE})
        return recorded_instruction, self._game_from_rows(rows, fallback=game)

    def record_organizer_instruction_outcome(
        self, *, instruction: OrganizerInstruction, outbound_message: OutboundMessage
    ) -> OrganizerInstruction:
        """Commit an Organizer Instruction and outcome intent together."""

        instruction_values = {f"instruction_{key}": value for key, value in asdict(instruction).items()}
        outbound_values = {f"outbound_{key}": value for key, value in asdict(outbound_message).items()}
        statement = f"""
            DECLARE instruction_is_new BOOL DEFAULT NOT EXISTS (
                SELECT 1 FROM `{self.table('organizer_instructions')}`
                WHERE source_message_key = @instruction_source_message_key
            );
            MERGE `{self.table('organizer_instructions')}` AS target
            USING (SELECT {', '.join(f'@instruction_{field} AS {field}' for field in asdict(instruction))}) AS source
            ON target.source_message_key = source.source_message_key
            WHEN NOT MATCHED THEN INSERT ({', '.join(asdict(instruction))}) VALUES ({', '.join(f'source.{field}' for field in asdict(instruction))});
            {self._outbound_merge(outbound_message)}
            SELECT * FROM `{self.table('organizer_instructions')}` WHERE source_message_key = @instruction_source_message_key;
        """
        rows = self.transaction_rows(statement, self._parameters({**instruction_values, **outbound_values}))
        if rows and str(rows[0]["id"]) != instruction.id:
            return OrganizerInstruction(**{**rows[0], "status": INSTRUCTION_DUPLICATE})
        return OrganizerInstruction(**rows[0]) if rows else instruction

    def _answer_outbound_insert(self, message: OutboundMessage) -> str:
        fields = tuple(asdict(message))
        return f"""
            INSERT INTO `{self.table('outbound_messages')}` ({', '.join(fields)})
            SELECT {', '.join(f'@outbound_{field}' for field in fields)}
            FROM (SELECT 1)
            WHERE instruction_is_new
              AND NOT EXISTS (SELECT 1 FROM `{self.table('outbound_messages')}` WHERE idempotency_key = @outbound_idempotency_key);
        """

    def _outbound_merge(self, message: OutboundMessage) -> str:
        fields = tuple(asdict(message))
        return f"""
            MERGE `{self.table('outbound_messages')}` AS target
            USING (SELECT {', '.join(f'@outbound_{field} AS {field}' for field in fields)}) AS source
            ON target.idempotency_key = source.idempotency_key
            WHEN NOT MATCHED THEN INSERT ({', '.join(fields)}) VALUES ({', '.join(f'source.{field}' for field in fields)});
        """

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
            FROM `{self.table('submissions')}` AS selected_submission
            WHERE selected_submission.source_message_key = @source_message_key
              AND selected_submission.is_eligible
              AND prior.game_id = selected_submission.game_id AND prior.player_id = selected_submission.player_id
              AND prior.is_eligible
              AND (
                prior.received_at < selected_submission.received_at
                OR (prior.received_at = selected_submission.received_at AND prior.source_message_key < selected_submission.source_message_key)
              );
            UPDATE `{self.table('submissions')}` AS selected_submission
            SET is_eligible = FALSE, ineligibility_reason = 'superseded', updated_at = @updated_at
            WHERE selected_submission.source_message_key = @source_message_key
              AND selected_submission.is_eligible
              AND EXISTS (
                SELECT 1 FROM `{self.table('submissions')}` AS later
                WHERE later.game_id = selected_submission.game_id AND later.player_id = selected_submission.player_id
                  AND later.is_eligible
                  AND (
                    later.received_at > selected_submission.received_at
                    OR (later.received_at = selected_submission.received_at AND later.source_message_key > selected_submission.source_message_key)
                  )
              );
            SELECT * FROM `{self.table('submissions')}` WHERE source_message_key = @source_message_key;
        """
        rows = self.transaction_rows(statement, self._parameters(values))
        if not rows:
            rows = self.query_rows(
                f"SELECT * FROM `{self.table('submissions')}` WHERE source_message_key = @source_message_key",
                self._parameters({"source_message_key": submission.source_message_key}),
            )
        if not rows:
            raise RuntimeError("Submission creation committed without a readable Submission row")
        return Submission(**rows[0])

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

    def find_latest_scored_game_before(self, *, day: Any) -> Game | None:
        rows = self.query_rows(
            f"""SELECT * FROM `{self.table('games')}`
            WHERE day < @day AND status = 'scored' AND correct_option IS NOT NULL
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

    def publish_game(
        self, game: Game, *, series: Series | None = None, outbound_message: OutboundMessage | None = None
    ) -> Game:
        published = replace(game, status="published")
        values = asdict(published)
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
        series_statement, series_values, source_fields = self._publication_series_statement(
            series, source_fields, series_table=self.table("series")
        )
        statement = series_statement + f"""
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
                FROM (SELECT 1)
                WHERE NOT EXISTS (SELECT 1 FROM `{self.table('outbound_messages')}` WHERE idempotency_key = @outbound_idempotency_key);
            """
            values.update(outbound)
        statement += f"SELECT * FROM `{self.table('games')}` WHERE day = @day;"
        values.update(series_values)
        return self._game_from_rows(self.transaction_rows(statement, self._parameters(values)), fallback=published)

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

    def replace_pending_game(
        self, game: Game, *, series: Series | None = None, outbound_message: OutboundMessage | None = None
    ) -> Game:
        series_table = self.table('series')
        game_table = self.table("games")
        published = replace(game, status="published")
        values = asdict(published)
        fields = ", ".join(values)
        source_fields = ", ".join(
            f"PARSE_JSON(@{field}) AS {field}" if isinstance(values[field], dict) else f"@{field} AS {field}"
            for field in values
        )
        series_statement, series_values, source_fields = self._publication_series_statement(
            series, source_fields, series_table=series_table
        )
        statement = series_statement + f"""
            DELETE FROM `{game_table}` WHERE day = @day AND status = 'pending';
            INSERT INTO `{game_table}` ({fields}) SELECT {", ".join(f"source.{field}" for field in values)}
            FROM (SELECT {source_fields}) AS source
            WHERE NOT EXISTS (SELECT 1 FROM `{self.table('games')}` WHERE day = @day);
        """
        if outbound_message is not None:
            outbound = {f"outbound_{key}": value for key, value in asdict(outbound_message).items()}
            outbound_fields = tuple(asdict(outbound_message))
            statement += f"""
                INSERT INTO `{self.table('outbound_messages')}` ({", ".join(outbound_fields)})
                SELECT {", ".join(f"@outbound_{field}" for field in outbound_fields)}
                FROM (SELECT 1)
                WHERE NOT EXISTS (SELECT 1 FROM `{self.table('outbound_messages')}` WHERE idempotency_key = @outbound_idempotency_key);
            """
            values.update(outbound)
        statement += f"SELECT * FROM `{game_table}` WHERE day = @day;"
        values.update(series_values)
        return self._game_from_rows(self.transaction_rows(statement, self._parameters(values)), fallback=published)

    def _publication_series_statement(
        self, series: Series | None, source_fields: str, *, series_table: str
    ) -> tuple[str, dict[str, Any], str]:
        """Return the Series merge and Game source fields for one publication transaction."""

        if series is None:
            return "", {}, source_fields
        values = {f"series_{key}": value for key, value in asdict(series).items()}
        fields = tuple(asdict(series))
        game_source_fields = source_fields.replace(
            "@series_id AS series_id",
            f"(SELECT id FROM `{series_table}` WHERE name = @series_name) AS series_id",
        )
        statement = f"""
            MERGE `{series_table}` AS target
            USING (SELECT {', '.join(f'@series_{field} AS {field}' for field in fields)}) AS source
            ON target.name = source.name
            WHEN NOT MATCHED THEN INSERT ({', '.join(fields)}) VALUES ({', '.join(f'source.{field}' for field in fields)});
        """
        return statement, values, game_source_fields

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
                SELECT {", ".join(f"@event_{index}_{field}" for field in fields)} FROM (SELECT 1) WHERE transitioned;"""
            )
        for index, message in enumerate(outbound_messages):
            message_values = {f"outbound_{index}_{key}": value for key, value in asdict(message).items()}
            fields = tuple(asdict(message))
            statements.append(
                f"""INSERT INTO `{self.table("outbound_messages")}` ({", ".join(fields)})
                SELECT {", ".join(f"@outbound_{index}_{field}" for field in fields)} FROM (SELECT 1) WHERE transitioned;"""
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

    def record_instruction_score_event(
        self, *, player: Player, instruction: OrganizerInstruction, event: ScoreEvent
    ) -> ScoreEvent:
        player_values = {f"player_{key}": value for key, value in asdict(player).items()}
        instruction_values = {f"instruction_{key}": value for key, value in asdict(instruction).items()}
        event_values = {f"event_{key}": value for key, value in asdict(event).items()}
        statement = f"""
            DECLARE instruction_is_new BOOL DEFAULT NOT EXISTS (
                SELECT 1 FROM `{self.table('organizer_instructions')}`
                WHERE source_message_key = @instruction_source_message_key
            );
            MERGE `{self.table('players')}` AS target
            USING (SELECT {', '.join(f'@player_{field} AS {field}' for field in asdict(player))}) AS source
            ON target.email = source.email
            WHEN NOT MATCHED THEN INSERT ({', '.join(asdict(player))}) VALUES ({', '.join(f'source.{field}' for field in asdict(player))});
            MERGE `{self.table('organizer_instructions')}` AS target
            USING (SELECT {', '.join(f'@instruction_{field} AS {field}' for field in asdict(instruction))}) AS source
            ON target.source_message_key = source.source_message_key
            WHEN NOT MATCHED THEN INSERT ({', '.join(asdict(instruction))}) VALUES ({', '.join(f'source.{field}' for field in asdict(instruction))});
            INSERT INTO `{self.table('score_events')}` ({', '.join(asdict(event))})
            SELECT {', '.join(f'@event_{field}' if field != 'player_id' else '(SELECT id FROM `' + self.table('players') + '` WHERE email = @player_email)' for field in asdict(event))}
            FROM (SELECT 1)
            WHERE instruction_is_new
              AND NOT EXISTS (SELECT 1 FROM `{self.table('score_events')}` WHERE idempotency_key = @event_idempotency_key);
            SELECT * FROM `{self.table('score_events')}` WHERE idempotency_key = @event_idempotency_key;
        """
        rows = self.transaction_rows(statement, self._parameters({**player_values, **instruction_values, **event_values}))
        return ScoreEvent(**rows[0]) if rows else event

    def record_manual_score_event_instruction(
        self, *, player: Player, instruction: OrganizerInstruction, event: ScoreEvent, outbound_message: OutboundMessage
    ) -> tuple[ScoreEvent, bool]:
        """Atomically process a Manual Score Event Instruction and its outcome."""

        player_values = {f"player_{key}": value for key, value in asdict(player).items()}
        instruction_values = {f"instruction_{key}": value for key, value in asdict(instruction).items()}
        event_values = {f"event_{key}": value for key, value in asdict(event).items()}
        outbound_values = {f"outbound_{key}": value for key, value in asdict(outbound_message).items()}
        statement = f"""
            DECLARE instruction_is_new BOOL DEFAULT NOT EXISTS (
                SELECT 1 FROM `{self.table('organizer_instructions')}`
                WHERE source_message_key = @instruction_source_message_key
            );
            MERGE `{self.table('players')}` AS target
            USING (SELECT {', '.join(f'@player_{field} AS {field}' for field in asdict(player))}) AS source
            ON target.email = source.email
            WHEN NOT MATCHED THEN INSERT ({', '.join(asdict(player))}) VALUES ({', '.join(f'source.{field}' for field in asdict(player))});
            MERGE `{self.table('organizer_instructions')}` AS target
            USING (SELECT {', '.join(f'@instruction_{field} AS {field}' for field in asdict(instruction))}) AS source
            ON target.source_message_key = source.source_message_key
            WHEN NOT MATCHED THEN INSERT ({', '.join(asdict(instruction))}) VALUES ({', '.join(f'source.{field}' for field in asdict(instruction))});
            INSERT INTO `{self.table('score_events')}` ({', '.join(asdict(event))})
            SELECT {', '.join(f'@event_{field}' if field != 'player_id' else '(SELECT id FROM `' + self.table('players') + '` WHERE email = @player_email)' for field in asdict(event))}
            FROM (SELECT 1)
            WHERE instruction_is_new
              AND NOT EXISTS (SELECT 1 FROM `{self.table('score_events')}` WHERE idempotency_key = @event_idempotency_key);
            MERGE `{self.table('outbound_messages')}` AS target
            USING (SELECT {', '.join(f'@outbound_{field} AS {field}' for field in asdict(outbound_message))}) AS source
            ON target.idempotency_key = source.idempotency_key
            WHEN NOT MATCHED THEN INSERT ({', '.join(asdict(outbound_message))}) VALUES ({', '.join(f'source.{field}' for field in asdict(outbound_message))});
            SELECT score_events.*, instruction_is_new AS instruction_is_new
            FROM `{self.table('score_events')}` AS score_events
            WHERE idempotency_key = @event_idempotency_key;
        """
        rows = self.transaction_rows(
            statement, self._parameters({**player_values, **instruction_values, **event_values, **outbound_values})
        )
        if not rows:
            return event, False
        applied = bool(rows[0].pop("instruction_is_new"))
        return ScoreEvent(**rows[0]), applied

    def record_outbound_message(self, message: OutboundMessage) -> OutboundMessage:
        self._merge_record(table_name="outbound_messages", key="idempotency_key", values=asdict(message))
        return message

    def find_outbound_message(self, *, idempotency_key: str) -> OutboundMessage | None:
        rows = self.query_rows(
            f"SELECT * FROM `{self.table('outbound_messages')}` WHERE idempotency_key = @idempotency_key",
            self._parameters({"idempotency_key": idempotency_key}),
        )
        return OutboundMessage(**rows[0]) if rows else None

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
        reconciled = self.find_outbound_message(idempotency_key=idempotency_key)
        if reconciled is None:
            raise RuntimeError("Outbound Message disappeared during reconciliation")
        return reconciled

    def read_score_events_for_game(self, *, game_id: str) -> tuple[ScoreEvent, ...]:
        rows = self.query_rows(
            f"SELECT * FROM `{self.table('score_events')}` WHERE game_id = @game_id",
            self._parameters({"game_id": game_id}),
        )
        return tuple(ScoreEvent(**row) for row in rows)

    def read_scoreboard(self, *, series_id: str) -> tuple[ScoreboardEntry, ...]:
        rows = self.query_rows(
            f"""
            WITH scoreboard_players AS (
              SELECT games.series_id, submissions.player_id
              FROM `{self.table('submissions')}` AS submissions
              JOIN `{self.table('games')}` AS games ON games.id = submissions.game_id
              UNION DISTINCT
              SELECT series_id, player_id FROM `{self.table('score_events')}`
            )
            SELECT
              scoreboard_players.series_id,
              players.id AS player_id,
              players.email,
              players.nickname,
              COALESCE(SUM(score_events.points_delta), 0) AS score
            FROM scoreboard_players
            JOIN `{self.table('players')}` AS players ON players.id = scoreboard_players.player_id
            LEFT JOIN `{self.table('score_events')}` AS score_events
              ON score_events.player_id = players.id
              AND score_events.series_id = scoreboard_players.series_id
            WHERE scoreboard_players.series_id = @series_id
            GROUP BY scoreboard_players.series_id, players.id, players.email, players.nickname
            ORDER BY score DESC, players.email
            """,
            self._parameters({"series_id": series_id}),
        )
        return tuple(ScoreboardEntry(**row) for row in rows)

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
