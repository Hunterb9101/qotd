# Behavior specifications

Behavior specifications define the observable contract for a QOTD change.
They are the forward-looking source of intent; Git history records why and
when the contract evolved.

Use one focused file per behavior or closely related behavior boundary.

- Prefer `kebab-case.feature` written in Gherkin. State the relevant context,
  event, and observable outcome with `Given`, `When`, and `Then`.
- Use `kebab-case.md` only when Gherkin makes the contract less clear. Include
  **Context**, **When**, **Then**, and any material **Boundary** or exception.
- Link the behavior to deterministic acceptance coverage when possible. Do not
  describe implementation steps, proposed abstractions, or future work.

Use Git history for prior context; do not add ADRs or PRDs.
