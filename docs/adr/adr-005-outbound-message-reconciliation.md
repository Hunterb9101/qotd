# ADR-005: Reconcile Outbound QOTD Messages

- Status: Accepted
- Date: 2026-08-09

## Context

BigQuery transactions cannot include Gmail publication. A workflow can commit
state and fail while sending an email, or Gmail can accept an email while the
workflow fails before recording the result. Retrying without durable intent
state risks duplicate Question publication or duplicate Organizer messages.

## Decision

Every external QOTD email uses an `outbound_messages` record as a durable
intent. The record is created in the same BigQuery transaction as the state
transition that requires the email and is keyed by a deterministic
idempotency key.

The workflow renders the exact recipient, subject, and body from that intent,
then sends it through Gmail. On success, it records the hashed Gmail message
identity, send time, and `sent` status in a second idempotent transaction.

When a retry encounters a pending intent, it reconciles Gmail before sending:

- Question publication searches sent mail using the exact Question subject and
  the persisted Game publication details.
- Other outbound messages search for their persisted recipient, subject, and
  rendered body within the intent's send window.

If reconciliation finds the message, the workflow marks the intent sent. If
it cannot establish whether Gmail accepted the message, it fails closed and
leaves the intent pending for explicit operator recovery; it does not send a
second copy.

## Consequences

- Question publication and Organizer messages are idempotent across workflow
  retries.
- The exact outbound body is retained for audit and Gmail reconciliation.
- A pending outbound intent is an observable operational state, not a reason
  to infer publication from a timestamp or send again.
- Gmail search remains a recovery mechanism, not the canonical source of
  QOTD state.
