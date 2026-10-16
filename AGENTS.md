# Guidance
- NEVER adjust the `tests/guardrails` directory without explicit approval.
- Use the terms in [docs/DEFINITIONS.md](docs/DEFINITIONS.md) for new QOTD
  documentation and implementation. Existing code and documentation may still
  use inconsistent or legacy terminology. Update terms when adjusting those sections of code.

## Behavior Specifications

- Define or update a behavior specification in `behaviors/` before changing a
  user-visible or operational behavior. Prefer a Gherkin `.feature` file; use
  Markdown only when Gherkin would obscure the behavior.
- A Markdown behavior specification must state the context, triggering event,
  expected outcome, and relevant boundary or exception. Keep either format
  focused on observable behavior rather than implementation steps.
- Add or update deterministic acceptance coverage for the specified behavior
  when it can be exercised without live credentials or provider access.
- Do not create ADRs or PRDs. Use Git history to understand prior decisions and
  behavior changes.

## Code Review Rules

- Review changes primarily for architecture, contracts, and functionality.
- Treat a behavior specification and its acceptance coverage as the source of
  intent for a behavior change. Flag a changed contract that lacks either a
  corresponding behavior specification or appropriate coverage.
- Flag unnecessary abstractions, configuration, dependencies, persistence, or
  extensibility that no specified behavior requires. Do not request design
  patterns or future-proofing without a demonstrated need.
- Do not treat formatting, naming preference, or a documentation-only rewrite
  as a review finding unless it changes a contract or creates a concrete risk.
