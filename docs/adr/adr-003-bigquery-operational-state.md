# ADR-003: Use BigQuery DML for Canonical QOTD State

- Status: Accepted
- Date: 2026-08-09

## Context

QOTD currently writes append-only snapshots to BigQuery and derives current
state from the latest row. That approach does not reliably connect an
Organizer Instruction, its resulting Score Event, and a Player's resulting
Score. It also allows concurrent workflow runs to independently observe the
same pre-transition state.

The QOTD Game Lifecycle and State Journeys requires idempotent state
transitions, exactly one scored Game, and an auditable source for every Score.
QOTD will continue to use BigQuery as its operational database.

## Decision

BigQuery is QOTD's canonical operational database. The existing QOTD dataset
will be reset before the new model is introduced; no data backfill, dual-write
period, or backwards-compatibility layer is required.

All operational state changes must use parameterized GoogleSQL DML. A
multi-statement transaction is required when a transition changes more than one
table. `WRITE_APPEND` load jobs must not write operational state.

Each state-changing workflow must:

1. use an idempotency identity for its source message or workflow action;
2. claim or transition the affected Game row inside the transaction when the
   action concerns a Game;
3. write the resulting state and any Score Events in that same transaction;
4. commit before performing external side effects; and
5. retry a cancelled transaction using the same idempotency identity.

GitHub Actions concurrency settings remain a useful optimization, but they are
not a correctness boundary. The database transition is authoritative when a
scheduled workflow and a manually dispatched workflow overlap.

The exact table schema, late-Submission collection, rescoring policy, and
outbound-message reconciliation are separate decisions and require follow-on
ADRs.

## Consequences

- Current Scoreboard reads will be derived from immutable Score Events rather
  than writable score snapshots.
- Each operational table and DML query must be provisioned and maintained in
  version-controlled SQL.
- Application code must handle transaction-conflict retries without creating
  new idempotency identities.
- External side effects, including Question publication and Organizer email,
  cannot be committed atomically with BigQuery state and need a durable
  reconciliation design.
- BigQuery DML becomes part of the production workflow's required permissions,
  billing, testing, and operational monitoring.

## Alternatives Rejected

### Continue with append-only state snapshots

Rejected because a latest-row read cannot prove which Score Events contributed
to a Score or protect a Game from overlapping scoring runs.

### Move canonical state to a transactional database

Rejected because QOTD will retain BigQuery as its operational database.
