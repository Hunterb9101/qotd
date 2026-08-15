-- Canonical operational state for QOTD (ADR-004).
-- This script is executed with the target QOTD dataset as its default dataset.

CREATE TABLE IF NOT EXISTS series (
  id STRING NOT NULL,
  name STRING NOT NULL,
  starts_on DATE NOT NULL,
  ends_on DATE NOT NULL,
  created_at TIMESTAMP NOT NULL,
  updated_at TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS players (
  id STRING NOT NULL,
  email STRING NOT NULL,
  nickname STRING
);

CREATE TABLE IF NOT EXISTS ai_calls (
  id STRING NOT NULL,
  use_case STRING NOT NULL,
  prompt STRING NOT NULL,
  usecase_run_id STRING NOT NULL,
  provider STRING NOT NULL,
  model STRING NOT NULL,
  request JSON NOT NULL,
  response JSON,
  provider_request_id STRING,
  status STRING NOT NULL,
  error_type STRING,
  error_message STRING,
  started_at TIMESTAMP NOT NULL,
  completed_at TIMESTAMP NOT NULL,
  latency_ms INT64,
  input_tokens INT64,
  output_tokens INT64,
  total_tokens INT64
);

CREATE TABLE IF NOT EXISTS games (
  id STRING NOT NULL,
  series_id STRING NOT NULL,
  day DATE NOT NULL,
  status STRING NOT NULL,
  publication_mode STRING NOT NULL,
  question_prompt STRING,
  question_options JSON,
  publication_subject STRING,
  published_at TIMESTAMP,
  publication_message_key STRING,
  publication_instruction_id STRING,
  deadline_at TIMESTAMP NOT NULL,
  correct_option STRING,
  answer_source_url STRING,
  answer_source_note STRING,
  answer_instruction_id STRING,
  scored_at TIMESTAMP,
  created_at TIMESTAMP NOT NULL,
  updated_at TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS organizer_instructions (
  id STRING NOT NULL,
  source_message_key STRING NOT NULL,
  sender_email STRING NOT NULL,
  subject STRING NOT NULL,
  received_at TIMESTAMP NOT NULL,
  action STRING NOT NULL,
  status STRING NOT NULL,
  rejection_reason STRING,
  processed_at TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS submissions (
  id STRING NOT NULL,
  source_message_key STRING NOT NULL,
  game_id STRING NOT NULL,
  player_id STRING NOT NULL,
  body_text STRING NOT NULL,
  received_at TIMESTAMP NOT NULL,
  interpreted_option STRING,
  is_eligible BOOL NOT NULL,
  ineligibility_reason STRING,
  created_at TIMESTAMP NOT NULL,
  updated_at TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS score_events (
  id STRING NOT NULL,
  idempotency_key STRING NOT NULL,
  player_id STRING NOT NULL,
  series_id STRING NOT NULL,
  game_id STRING,
  submission_id STRING,
  organizer_instruction_id STRING,
  event_type STRING NOT NULL,
  points_delta INT64 NOT NULL,
  reason STRING,
  created_at TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS outbound_messages (
  id STRING NOT NULL,
  idempotency_key STRING NOT NULL,
  message_type STRING NOT NULL,
  game_id STRING,
  organizer_instruction_id STRING,
  recipient STRING NOT NULL,
  subject STRING NOT NULL,
  body_text STRING NOT NULL,
  status STRING NOT NULL,
  source_message_key STRING,
  created_at TIMESTAMP NOT NULL,
  sent_at TIMESTAMP
);

CREATE OR REPLACE VIEW scoreboard AS
WITH scoreboard_players AS (
  SELECT games.series_id, submissions.player_id
  FROM `{{PROJECT_ID}}.{{DATASET_ID}}.submissions` AS submissions
  JOIN `{{PROJECT_ID}}.{{DATASET_ID}}.games` AS games ON games.id = submissions.game_id
  UNION DISTINCT
  SELECT series_id, player_id
  FROM `{{PROJECT_ID}}.{{DATASET_ID}}.score_events`
)
SELECT
  scoreboard_players.series_id,
  players.id AS player_id,
  players.email,
  COALESCE(SUM(score_events.points_delta), 0) AS score
FROM scoreboard_players
JOIN `{{PROJECT_ID}}.{{DATASET_ID}}.players` AS players ON players.id = scoreboard_players.player_id
LEFT JOIN `{{PROJECT_ID}}.{{DATASET_ID}}.score_events` AS score_events
  ON score_events.player_id = players.id
  AND score_events.series_id = scoreboard_players.series_id
GROUP BY scoreboard_players.series_id, players.id, players.email
ORDER BY score DESC, players.email;
