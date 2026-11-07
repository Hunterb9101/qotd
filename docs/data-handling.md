# Data Handling and Retention

This document describes the operational data QOTD currently persists, the
access boundaries needed to operate it, and the decisions that the Organizer
must make before treating the system as a long-lived production service. It
uses the canonical-state model in
[operational-state behavior](../behaviors/operational-state.feature); it does not replace the
[Definitions](DEFINITIONS.md).

## Scope and current behavior

QOTD operates a private email game. The canonical BigQuery dataset is an
operational record, not an anonymized analytics store. The current schema has
no table or partition expiration, and QOTD has no implemented Player-data
deletion workflow. Consequently, the data below is retained indefinitely
unless an authorized operator deliberately changes or deletes it.

The Organizer must confirm the retention and deletion decisions in
[Decisions requiring Organizer confirmation](#decisions-requiring-organizer-confirmation)
before enabling production workflows. Until then, do not promise a retention
period or deletion deadline to Players.

## Persisted data

| Data | Where QOTD persists it | Why it is needed | Current retention |
| --- | --- | --- | --- |
| [Player](DEFINITIONS.md#player) email address | `players.email`; it also appears in the `scoreboard` view and may appear in message content | Identify a Player, associate [Submissions](DEFINITIONS.md#submission), calculate Scores, and render the Scoreboard | Indefinite; no deletion workflow is implemented. |
| Player Submission body, received time, and a one-way Gmail message-ID hash | `submissions` | Interpret, select, score, and audit a Submission; prevent duplicate collection | Indefinite; every Submission, including late and superseded ones, is retained. |
| [Outbound Message](DEFINITIONS.md#outbound-message) recipient, subject, body, Gmail message-ID hash, and delivery timestamps | `outbound_messages` | Reconcile delivery and prevent duplicate sends | Indefinite. The body can include the Question, Scoreboard, Player email addresses, or Organizer-facing scoring results. |
| [AI Call](DEFINITIONS.md#ai-call) prompt name, rendered provider request, provider response, errors, provider request ID, and usage/timing metadata | `ai_calls` | Audit AI behavior, troubleshoot failures, and account for provider use | Indefinite. AI requests for freeform-answer interpretation include the relevant Question and Player Submission text. Credentials are redacted before an AI Call is persisted. |
| [Organizer Instruction](DEFINITIONS.md#organizer-instruction) sender address, subject, received time, action, status, and a one-way Gmail message-ID hash | `organizer_instructions` | Authorize and audit Organizer actions and avoid duplicate processing | Indefinite. The original Organizer Instruction body is not retained in canonical state. |
| Game, Answer, [Score Event](DEFINITIONS.md#score-event), and [Series](DEFINITIONS.md#series) records | `games`, `score_events`, and `series` | Run QOTD, calculate Scores, and preserve an auditable game history | Indefinite. These records can be linked to Player email addresses through Submissions and Score Events. |

QOTD also reads email from Gmail and sends email through Gmail. Gmail retention,
Google Group archives, and the AI provider's handling of requests are governed
by their respective account settings and provider terms; they are not controlled
by the QOTD canonical dataset.

## Least-privilege access

Access should be separated by operational responsibility and granted only to
people and workloads that need it.

- The **Organizer** manages the private Google Group and approved Organizer
  addresses. Group membership and conversations should remain private.
- The QOTD runtime identity needs only the Gmail scopes documented in
  [For Organizers](for-organizers.md#google-cloud-platform), BigQuery access
  limited to the QOTD dataset, and an OpenAI API key limited to this QOTD
  project or organization where the provider supports that restriction.
- GitHub Actions secrets must be stored in the protected `production`
  environment, available only to the production workflows and maintainers who
  administer that environment. Do not copy OAuth refresh tokens or API keys
  into repository files, workflow logs, issues, or email.
- BigQuery dataset access should be limited to the runtime identity and a
  small set of authorized operators. Give read access only to people who need
  to investigate QOTD operations; give write or schema-change access only to
  maintainers responsible for state transitions and migrations.
- Operators should use a separate non-production dataset for integration
  testing, as described in [For Developers](for-developers.md#tests), and
  must not use production Player data in local fixtures or test datasets.

Review the people, identities, OAuth grants, GitHub environment access, and
BigQuery dataset roles at least when an Organizer or maintainer changes, and
revoke access that is no longer needed.

## Deletion and retention procedure

No routine purge is currently safe to run without an approved retention policy
and a tested deletion design. The canonical records are related: deleting a
Player, Submission, or Outbound Message can break Score Event auditability,
delivery reconciliation, or Scoreboard history.

Until a deletion workflow is implemented, an authorized operator handling a
deletion request or retention exception should:

1. Record the request, requesting identity, requested scope, approving
   Organizer, and completion status outside the affected canonical records.
2. Identify all affected canonical records and external copies: Gmail mailbox,
   Google Group archives, BigQuery tables and views, AI-provider records, and
   any exports or backups that are within the operator's control.
3. Decide whether the request can be satisfied without corrupting Game,
   Submission, Score Event, or Outbound Message audit trails. Escalate to the
   Organizer before changing canonical state.
4. Use a reviewed, reversible-or-tested migration or deletion procedure; do
   not ad hoc edit production tables. Verify the resulting Game lifecycle,
   Scores, and delivery reconciliation behavior.
5. Document what was deleted, what could not be deleted, applicable retention
   constraints, and the verification result. Coordinate requests concerning
   Gmail, Google Groups, or the AI provider through those systems' controls.

Before relying on this procedure for a real request, implement and test a
specific deletion or anonymization design approved by the Organizer. This
document does not make legal claims about whether a request must be honored.

## Incident response

Treat unintended disclosure of Player email addresses, Submission bodies,
Outbound Message content, Organizer data, AI Call records, or credentials as
a security incident.

1. Contain it: suspend the affected workflow where appropriate, remove public
   sharing, and revoke or rotate exposed OAuth credentials and API keys.
2. Preserve enough evidence for investigation without copying additional
   sensitive content into issues or chat. Record the affected systems,
   identities, time range, and known data categories.
3. Have the Organizer determine who needs to be notified and when, taking
   account of the affected accounts, participants, provider terms, and any
   applicable obligations.
4. Remediate the access path, validate least-privilege settings, and document
   recovery actions before resuming production workflows.

Do not place raw Submission text, email addresses, secrets, or complete AI
requests/responses in public GitHub issues, pull requests, or logs.

## Decisions requiring Organizer confirmation

The following are not yet product decisions. The Organizer must approve them,
and the implementation and this document must then be updated together.

- A retention period for each category above, including whether completed
  Series need indefinite audit history.
- Whether and how a former Player can request deletion or anonymization, and
  how Scores and Score Events should remain auditable after that change.
- Who is authorized to access production BigQuery data, Gmail, Google Group
  archives, GitHub production secrets, and AI-provider usage records.
- Whether the selected AI provider's retention and data-use settings are
  acceptable for Player Submission text and Questions.
- The incident-notification owner, contact method, and required response
  timeline.
- Backup, export, and recovery practices, including their retention and
  deletion behavior.
