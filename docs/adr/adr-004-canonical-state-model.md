# ADR-004: Adopt the Canonical QOTD State Model

- Status: Accepted
- Date: 2026-08-09

## Context

QOTD needs an operational state model that implements the adopted Game
lifecycle, supports idempotent BigQuery DML transactions, and makes every
Player Score auditable. The existing append-only snapshots do not provide
reliable relationships between Games, Organizer Instructions, Submissions, and
Score Events.

## Decision

QOTD will use the following canonical write tables. UUIDs are stored as
BigQuery `STRING` values.

### `series`

| Field | Type | Notes |
|---|---|---|
| `id` | `STRING` | UUID primary identifier. |
| `name` | `STRING` | Human-readable Series name. |
| `starts_on` | `DATE` | First Day in the Series. |
| `ends_on` | `DATE` | Last Day in the Series. |
| `created_at` | `TIMESTAMP` | Record creation time. |
| `updated_at` | `TIMESTAMP` | Most recent update time. |

### `players`

| Field | Type | Notes |
|---|---|---|
| `id` | `STRING` | UUID primary identifier. |
| `email` | `STRING` | Unique normalized email address. |
| `nickname` | `STRING NULL` | Reserved for a future feature. |

### `games`

| Field | Type | Notes |
|---|---|---|
| `id` | `STRING` | UUID primary identifier. |
| `series_id` | `STRING` | References `series.id`. |
| `day` | `DATE` | Unique Game Day. |
| `status` | `STRING` | `pending`, `published`, or `scored`. |
| `publication_mode` | `STRING` | `automated` or `manual`. |
| `question_prompt` | `STRING NULL` | Null while a manual Game is pending. |
| `question_options` | `JSON NULL` | The Question options. |
| `publication_subject` | `STRING NULL` | Published Question subject. |
| `published_at` | `TIMESTAMP NULL` | Question publication time. |
| `publication_message_key` | `STRING NULL` | Internal publication idempotency key. |
| `publication_instruction_id` | `STRING NULL` | Manual-publication source. |
| `deadline_at` | `TIMESTAMP` | Submission Deadline. |
| `correct_option` | `STRING NULL` | Answer option. |
| `answer_source_url` | `STRING NULL` | Answer source. |
| `answer_source_note` | `STRING NULL` | Optional Answer source context. |
| `answer_instruction_id` | `STRING NULL` | Manual-Answer source. |
| `scored_at` | `TIMESTAMP NULL` | Automatic scoring completion time. |
| `created_at` | `TIMESTAMP` | Record creation time. |
| `updated_at` | `TIMESTAMP` | Most recent state transition time. |

### `organizer_instructions`

| Field | Type | Notes |
|---|---|---|
| `id` | `STRING` | UUID primary identifier. |
| `source_message_key` | `STRING` | Unique one-way hash of Gmail message ID. |
| `sender_email` | `STRING` | Organizer address from Gmail. |
| `subject` | `STRING` | Email subject. |
| `received_at` | `TIMESTAMP` | Gmail received time. |
| `action` | `STRING` | Requested lifecycle action. |
| `status` | `STRING` | `applied`, `duplicate`, or `rejected`. |
| `rejection_reason` | `STRING NULL` | Stable rejection reason. |
| `processed_at` | `TIMESTAMP` | Final processing time. |

The original Organizer Instruction body is not retained.

### `submissions`

| Field | Type | Notes |
|---|---|---|
| `id` | `STRING` | UUID primary identifier. |
| `source_message_key` | `STRING` | Unique one-way hash of Gmail message ID. |
| `game_id` | `STRING` | References `games.id`. |
| `player_id` | `STRING` | References `players.id`. |
| `body_text` | `STRING` | Original Player Submission body. |
| `received_at` | `TIMESTAMP` | Gmail received time. |
| `interpreted_option` | `STRING NULL` | Interpreted option, when available. |
| `is_eligible` | `BOOL` | Whether the Submission can be scored. |
| `ineligibility_reason` | `STRING NULL` | `late` or `superseded` when ineligible. |
| `created_at` | `TIMESTAMP` | Record creation time. |
| `updated_at` | `TIMESTAMP` | Most recent classification time. |

### `score_events`

| Field | Type | Notes |
|---|---|---|
| `id` | `STRING` | UUID primary identifier. |
| `idempotency_key` | `STRING` | Unique retry safeguard. |
| `player_id` | `STRING` | References `players.id`. |
| `series_id` | `STRING` | References `series.id`. |
| `game_id` | `STRING NULL` | References `games.id` when applicable. |
| `submission_id` | `STRING NULL` | Automatic-scoring source. |
| `organizer_instruction_id` | `STRING NULL` | Manual-event source. |
| `event_type` | `STRING` | `automatic` or `manual`. |
| `points_delta` | `INT64` | Positive, zero, or negative delta. |
| `reason` | `STRING NULL` | Required for manual events. |
| `created_at` | `TIMESTAMP` | Event creation time. |

### `outbound_messages`

| Field | Type | Notes |
|---|---|---|
| `id` | `STRING` | UUID primary identifier. |
| `idempotency_key` | `STRING` | Unique retry safeguard. |
| `message_type` | `STRING` | Question publication, Organizer update, or Organizer Instruction outcome. |
| `game_id` | `STRING NULL` | References `games.id` when applicable. |
| `organizer_instruction_id` | `STRING NULL` | References its source when applicable. |
| `recipient` | `STRING` | Delivery address. |
| `subject` | `STRING` | Outbound email subject. |
| `body_text` | `STRING` | Exact rendered outbound email body. |
| `status` | `STRING` | `pending` or `sent`. |
| `source_message_key` | `STRING NULL` | One-way hash of Gmail message ID after send. |
| `created_at` | `TIMESTAMP` | Intent creation time. |
| `sent_at` | `TIMESTAMP NULL` | Confirmed send time. |

### `scoreboard` view

`scoreboard` is a standard BigQuery view, not a write table. For each Series,
it derives Players from Submissions and Score Events, left-joins Score Events,
sums `points_delta`, and orders the resulting Scores.

## Invariants and Write Rules

- `players.email`, `games.day`, incoming `source_message_key` values, and
  `score_events.idempotency_key` are unique logical keys.
- Each Game belongs to one Series and may have only one Answer.
- An automatic Score Event links to its Game and Submission; a manual Score
  Event links to its Organizer Instruction and may be Series-wide.
- Every Player Submission is retained, including late and superseded
  Submissions.
- Source-message hashes are retained only for idempotency; Organizer-facing
  diagnostics use sender, subject, Gmail received time, action, and outcome.
- Every external email has one `outbound_messages` intent before it is sent.
- BigQuery constraints are not the correctness boundary. The DML transactions
  required by ADR-003 must validate and enforce these rules.

## Consequences

- The old `questions`, `monthly_scores`, `reply_processing`,
  `manual_adjustments`, and `correct_answer_updates` tables are replaced when
  the dataset is reset.
- The application has one auditable path from a Score Event to its source
  Submission or Organizer Instruction.
- The Scoreboard can include active Players with zero or negative Scores.
- The table schema must be provisioned in version-controlled SQL before the
  new workflows are implemented.
