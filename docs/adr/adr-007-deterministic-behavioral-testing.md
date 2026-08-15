# ADR-007: Adopt Deterministic Behavioral Acceptance Testing

- Status: Accepted
- Date: 2026-08-15

## Context

QOTD has focused unit and adapter tests, but recent regressions showed that
individually correct components do not establish that a complete Game journey
satisfies the PRD. Important behavior crosses Gmail message classification,
canonical state transitions, AI interpretation, rendering, and retry
boundaries. Tests organized only around individual modules can miss failures
in those handoffs.

The existing `InMemoryCanonicalState` in `tests/support.py` already implements
substantial canonical-state behavior. Keeping that implementation in a generic
test-support module obscures its role and allows it to diverge from the
production `CanonicalState` contract.

QOTD cannot currently rely on unattended Gmail integration tests. The OAuth
refresh token expires every seven days while the Google application remains
unpublished, as tracked by [GitHub issue #3](https://github.com/Hunterb9101/qotd/issues/3).
Requiring those credentials for normal test runs would make the suite
unreliable and would not provide a stable correctness boundary.

## Decision

QOTD will add a deterministic behavioral acceptance-test layer that exercises
complete PRD journeys through source-backed adapters and stateful test
collaborators.

### In-memory canonical state

`InMemoryCanonicalState` will move from `tests/support.py` to
`qotd/external/storage/memory.py` and be renamed `InMemoryAdapter`. It will
implement the same `CanonicalState` interface used by `BQAdapter` and enforce
the canonical invariants required by ADR-004.

`InMemoryAdapter` is a supported source implementation for deterministic tests
and local development. This decision does not make it a production storage
backend or require a CLI option for selecting it.

Focused tests for `InMemoryAdapter` will live with the existing storage tests
under `tests/external/storage/`. QOTD will not introduce a separate
`tests/contracts/` hierarchy at this time. Shared behavioral tests may be
extracted later when `InMemoryAdapter` and `BQAdapter` can be exercised
reliably against the same cases.

### Acceptance-test organization

Multi-step behavioral tests will live under `tests/acceptance/`, separate from
focused domain, use-case, presentation, and external-adapter tests. Reusable
acceptance infrastructure will live in a purpose-named harness package under
that directory rather than in a generic `support.py` module.

The harness may provide stateful collaborators such as:

- a scenario object that coordinates a complete Game journey;
- a mailbox that records received, sent, unread, and handled messages;
- a scripted AI client that returns deterministic results or failures; and
- builders for Players, Games, Submissions, Organizer Instructions, and
  outbound messages.

These collaborators will model externally observable behavior. Tests will
assert canonical state, message state, and rendered outcomes rather than mock
call sequences or private implementation details.

The initial acceptance scenarios will cover:

1. an automated daily Game cycle from Question publication through scoring and
   the following Player recap;
2. isolation between Player Submissions and Organizer Instructions;
3. manual publication suppression and outbound-message recovery; and
4. final-weekday Winner announcement and the next monthly Series.

### PRD traceability

Acceptance tests will identify the PRD requirements they cover with a
registered `requirements` pytest marker. Requirement markers provide
traceability metadata and do not control default test selection.

Deterministic acceptance tests will run in the default test suite. Tests that
require live credentials, provider access, or incur external cost will retain
an execution-category marker such as `intg` and will not be treated as the sole
verification of a PRD requirement.

### Time-dependent behavior

Acceptance scenarios will use explicit dates and timestamps to verify
application decisions, including:

- whether a Submission received before the Deadline is eligible;
- whether a Submission received at or after the Deadline is late;
- whether a late Submission leaves an earlier eligible Submission selected;
- whether UTC message timestamps are classified against Mountain time
  correctly; and
- whether weekend and month-boundary transitions select the correct Game and
  Series.

QOTD will introduce a clock abstraction only where a direct current-time read
prevents deterministic testing. These tests do not claim to prove that GitHub
Actions starts a workflow at its configured wall-clock time. Workflow
scheduling remains an operational configuration and monitoring concern.

### External integration

Live Gmail integration will remain manual and non-gating until
[issue #3](https://github.com/Hunterb9101/qotd/issues/3) provides durable
unattended authentication. Existing BigQuery dry-run and isolated-storage
checks will remain in place. A dedicated external test environment and shared
cross-adapter behavioral suite are deferred decisions, not prerequisites for
the deterministic acceptance layer.

## Consequences

- PRD behavior gains executable coverage across use-case and rendering
  boundaries without depending on external credentials.
- `InMemoryAdapter` becomes maintained application source and must remain
  aligned with `CanonicalState` and ADR-004.
- Acceptance tests can detect regressions that focused unit tests and SQL
  validation do not expose.
- Requirement coverage becomes reviewable without excluding deterministic
  tests from the default suite.
- The deterministic environment cannot prove Gmail, BigQuery, OpenAI, or
  GitHub Actions availability and configuration. Focused integration checks
  remain necessary where feasible.
- Stateful test collaborators require care: they must model required behavior
  without reproducing implementation details unnecessarily.

## Alternatives Rejected

### Add more isolated mocks

Rejected because interaction-based mocks would couple tests to call sequences
without proving the resulting Game, Submission, Score Event, or Outbound
Message behavior.

### Require live end-to-end tests for PRD behavior

Rejected because expiring Gmail credentials make those tests unreliable, and
provider access would add latency, cost, and nondeterminism to normal test
runs.

### Keep the in-memory implementation in `tests/support.py`

Rejected because it is a substantial `CanonicalState` implementation rather
than a small fixture, and its behavior is central to deterministic acceptance
testing.

### Create a separate contract-test hierarchy immediately

Rejected for now because only the in-memory implementation can run reliably in
the default suite. Shared adapter contracts can be extracted when a stable
BigQuery test environment makes the additional structure useful.
