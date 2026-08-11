# ADR-006: Collect Late Player Submissions for Auditability

- Status: Accepted
- Date: 2026-08-09

## Context

QOTD must retain every Player Submission so it can explain why a response was
not scored. A scheduled scoring run naturally finds Submissions before the
Deadline, but a Player can reply after the Game is scored. Without a later
collection pass, that late Submission never reaches the database.

## Decision

Each scoring workflow includes a Submission-collection pass for every
published Game in the current Series and immediately preceding Series. The
pass queries Gmail for candidate replies, records each new Player Submission
idempotently, and classifies it using the Game Deadline.

A Submission received at or after the Deadline is recorded with
`is_eligible = false` and `ineligibility_reason = late`. A later eligible
Submission causes earlier eligible Submissions from that Player and Game to be
classified as `superseded`.

The collection pass never creates or changes automatic Score Events for an
already scored Game. An on-demand collection command for a specified Day is
available to investigate older Games outside the rolling two-Series window.

## Consequences

- The database can answer why a recently late Player Submission was not
  scored without reconstructing mailbox history during an investigation.
- Repeated sweeps are safe because Submission source-message keys are
  idempotent.
- The rolling window bounds normal Gmail work while the on-demand command
  preserves an audit path for older Games.
- A late Submission remains an audit fact; it never changes an already scored
  Game or Score Event.
