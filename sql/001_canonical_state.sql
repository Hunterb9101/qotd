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
  cached_input_tokens INT64,
  output_tokens INT64,
  total_tokens INT64,
  web_search_calls INT64
);

-- CREATE TABLE does not add fields to an existing table.
ALTER TABLE ai_calls ADD COLUMN IF NOT EXISTS cached_input_tokens INT64;
ALTER TABLE ai_calls ADD COLUMN IF NOT EXISTS web_search_calls INT64;

CREATE TABLE IF NOT EXISTS ai_pricing_rates (
  provider STRING NOT NULL,
  model STRING NOT NULL,
  effective_at TIMESTAMP NOT NULL,
  input_cost_per_million_tokens NUMERIC NOT NULL,
  cached_input_cost_per_million_tokens NUMERIC NOT NULL,
  output_cost_per_million_tokens NUMERIC NOT NULL,
  web_search_call_cost_usd NUMERIC NOT NULL
);

MERGE ai_pricing_rates AS target
USING (
  SELECT "openai" AS provider, "gpt-5.4" AS model, TIMESTAMP("2026-03-05") AS effective_at,
    NUMERIC '2.50' AS input_cost_per_million_tokens,
    NUMERIC '0.25' AS cached_input_cost_per_million_tokens,
    NUMERIC '15.00' AS output_cost_per_million_tokens,
    NUMERIC '0.01' AS web_search_call_cost_usd
  UNION ALL
  SELECT "openai", "gpt-5.4-mini", TIMESTAMP("2026-03-17"),
    NUMERIC '0.75', NUMERIC '0.075', NUMERIC '4.50', NUMERIC '0.01'
) AS source
ON target.provider = source.provider
  AND target.model = source.model
  AND target.effective_at = source.effective_at
WHEN NOT MATCHED THEN
  INSERT (
    provider, model, effective_at, input_cost_per_million_tokens,
    cached_input_cost_per_million_tokens, output_cost_per_million_tokens, web_search_call_cost_usd
  )
  VALUES (
    source.provider, source.model, source.effective_at, source.input_cost_per_million_tokens,
    source.cached_input_cost_per_million_tokens, source.output_cost_per_million_tokens,
    source.web_search_call_cost_usd
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

CREATE OR REPLACE VIEW ai_call_costs AS
SELECT
  ai_calls.id,
  ai_calls.use_case,
  ai_calls.prompt,
  ai_calls.usecase_run_id,
  ai_calls.provider,
  ai_calls.model,
  ai_calls.status,
  ai_calls.started_at,
  ai_calls.completed_at,
  ai_calls.latency_ms,
  ai_calls.input_tokens,
  ai_calls.cached_input_tokens,
  ai_calls.output_tokens,
  ai_calls.total_tokens,
  ai_calls.web_search_calls,
  rates.effective_at AS pricing_effective_at,
  CASE
    WHEN rates.provider IS NULL
      OR ai_calls.input_tokens IS NULL
      OR ai_calls.output_tokens IS NULL THEN NULL
    ELSE (
      GREATEST(ai_calls.input_tokens - COALESCE(ai_calls.cached_input_tokens, 0), 0)
        * rates.input_cost_per_million_tokens
      + COALESCE(ai_calls.cached_input_tokens, 0)
        * rates.cached_input_cost_per_million_tokens
      + ai_calls.output_tokens * rates.output_cost_per_million_tokens
    ) / 1000000
      + COALESCE(ai_calls.web_search_calls, 0) * rates.web_search_call_cost_usd
  END AS estimated_cost_usd
FROM `{{PROJECT_ID}}.{{DATASET_ID}}.ai_calls` AS ai_calls
LEFT JOIN `{{PROJECT_ID}}.{{DATASET_ID}}.ai_pricing_rates` AS rates
  ON rates.provider = ai_calls.provider
  AND rates.model = ai_calls.model
  AND rates.effective_at <= ai_calls.started_at
QUALIFY ROW_NUMBER() OVER (PARTITION BY ai_calls.id ORDER BY rates.effective_at DESC) = 1;
