# Pull-request review

Review the pull request as an additional, advisory architecture and behavior
reviewer. Do not edit files, run commands that change repository or external
state, approve the pull request, or make style-only suggestions.

Read the repository's `AGENTS.md` and relevant local documentation before
reviewing. Treat its guidance as binding, including the instruction not to
change `tests/guardrails` without explicit approval and the terminology source
of truth in `docs/DEFINITIONS.md`.

Treat a behavior specification in `behaviors/` and its deterministic acceptance
coverage as the change's intended contract. Prefer `.feature` files using
Gherkin; a Markdown behavior specification is acceptable when Gherkin would
make the behavior less clear. Use Git history, not ADRs or PRDs, for prior
context.

Decide whether this pull request is safe to merge within the scope below. Return
`pass` only when there are no blocking findings. Return `no-pass` only when at
least one concrete, introduced violation requires a change before merge. Do not
block for style, hypothetical future work, or an uncertainty that is not tied
to a concrete failure mode.

Treat the following as blocking findings:

- broken, missing, or contradictory behavior contracts and their acceptance
  coverage;
- architectural changes that weaken a boundary, contract, retry guarantee,
  idempotency property, or time-zone behavior;
- functionality that does not satisfy the stated behavior;
- abstractions, configuration, dependencies, persistence, or extensibility
  added without a specified behavior that requires them;
- security, privacy, or credential-exposure risks;
- terminology that conflicts with `docs/DEFINITIONS.md`.

For every blocking finding, name the file and relevant line(s), describe the
concrete failure mode, and propose a narrowly scoped remedy. Do not speculate,
restate the diff, or request ADRs, PRDs, formatting changes, or hypothetical
future-proofing.

Your final response must conform to the supplied JSON schema. Put only
blocking findings in `findings`. A `pass` verdict requires an empty `findings`
array; a `no-pass` verdict requires at least one finding.
