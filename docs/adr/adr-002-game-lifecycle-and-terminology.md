# ADR-002: Adopt the QOTD Game Lifecycle and Terminology Standard

- Status: Accepted
- Date: 2026-08-09

## Context

QOTD's current implementation and documentation use inconsistent terms and
model related work as disconnected commands. Recent failures in correct-answer
and score handling showed that this makes state transitions, retries, and
auditing difficult to reason about.

QOTD needs one shared vocabulary and one lifecycle-oriented description of
behavior before its operational state and database writes are redesigned.

## Decision

[QOTD Definitions](../DEFINITIONS.md) is the source of truth for QOTD
terminology. New documentation and implementation must use those terms. When
changing an existing section that uses legacy terminology, update that section
to the defined terms.

[QOTD Game Lifecycle and State Journeys](../game-lifecycle.md) is the
standard description of the QOTD game cycle. It governs the ordering and
required outcomes of:

- creating and publishing a Game through either the automated or manual path;
- collecting Player Submissions;
- closing and scoring a Game;
- processing Organizer Instructions and recovery actions; and
- displaying results without mutating Game or Score Event state.

The lifecycle document records agreed behavior and state transitions. It must
not become a catch-all for unresolved architecture decisions, database schema,
or alternative designs. Those decisions require their own ADRs.

## Consequences

- Future state tables, writes, and idempotency boundaries must be derived from
  the lifecycle, rather than defining the lifecycle implicitly.
- `Submission` is reserved for a Player response; an Organizer sends an
  Organizer Instruction that may set an Answer.
- Existing code and documentation may retain legacy terms until the relevant
  sections are changed, but new work must not introduce them.
- ADR-003 through ADR-006 decide the operational database, canonical state,
  outbound-message reconciliation, and late-Submission collection. Rescore
  policy requires a later ADR.
