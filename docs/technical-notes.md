# QOTD Technical Implementation Specification

## 1. Status and Scope

This document is the authoritative implementation specification for the MVP described in [docs/prd-initial.md](docs/prd-initial.md). When this document and the current code disagree, the code must be changed to match this document. Product behavior remains governed by the PRD; this document defines how that behavior is implemented.

The MVP is a Python command-line application run by scheduled GitHub Actions workflows. It has no web application or participant-management UI.

Normative terms such as **must**, **must not**, and **should** describe required and recommended behavior.

## 2. Architecture

The application is divided into four layers:

- `qotd/domain`: business models, date rules, scoring, and deterministic validation. Domain code must not call Gmail, Google Contacts, BigQuery, OpenAI, or web-search APIs.
- `qotd/usecases`: orchestration for one business workflow. Use cases receive external capabilities through configuration or injected interfaces so they can be tested without live services.
- `qotd/external`: adapters for Gmail, Google Contacts, BigQuery, OpenAI, and web search.
- `qotd/presentation`: email construction, templates, and organizer-report rendering.

Prompts used at runtime must live inside the `qotd` package beside the use case or adapter that owns them. Runtime code must not depend on repository-level `docs/prompts` paths.

## 3. Runtime and External Services

- Runtime: Python.
- Scheduling: GitHub Actions.
- Email: Gmail API using OAuth user consent for `***SECRET***` unless delegated service-account access is proven to work for the account.
- Participants: a named Google Contacts group accessed through the Google People API.
- Persistent state: BigQuery.
- Language model: OpenAI structured outputs behind the existing provider-neutral `LLMClient` interface.
- Research: a web-search adapter behind a provider-neutral `WebSearchClient` interface.
- Time zone: `America/Denver`/Mountain time for all game dates and schedules.

Credentials and service configuration must be supplied through environment variables or explicit CLI options. Secrets must not be committed.

## 4. Scheduled Workflows

### 4.1 Morning management and scoring

On weekdays:

1. Before 8:00 AM Mountain, process approved correct-answer and score-adjustment emails.
2. At 8:00 AM Mountain, score the previous game day's responses and send an organizer-only update.
3. Monday scoring uses the previous Friday. Weekends are skipped. Holidays are not special-cased in the MVP.

### 4.2 Noon question send

At 12:00 PM Mountain on weekdays, the send-question workflow must:

1. Calculate the participant subject using the shared subject builder: `QOTD - YYYY-MM-DD`, where the date is the current Mountain-time game date.
2. Search sent mail for an exact subject match for that game date.
3. If an exact match exists, treat it as the day's already-sent QOTD, persist it as a manual question when it is not already stored, log an explicit skip reason, and do not generate or send another question.
4. If no exact match exists, generate, validate, send, and store one question.

All participant-facing question emails, whether composed by automation or by the organizer, must use the same exact subject convention. Organizer scoring updates, alerts, confirmations, and management messages must use other subject prefixes and therefore cannot match the question search.

Detection must not use a broad `subject:QOTD` query or infer authorship from the sender alone. The exact dated subject is the detection heuristic and idempotency boundary.

## 5. Participant Source

The named Google Contacts group is the canonical participant list.

- The noon workflow must resolve and normalize all email addresses from the configured group before sending.
- The scoring workflow must score replies only from addresses present in that group.
- Email comparison must be case-insensitive after normalization.
- Explicit participant addresses may be injected in tests and local dry runs, but production must use the configured Google Contacts group.
- An empty or inaccessible group is an operational failure. The system must alert the organizer and must not send a participant email.
- The organizer update must report group members with no eligible reply as non-respondents.

Reply-sender discovery is not a participant-management mechanism and must not make an unknown sender eligible for scoring.

## 6. Email Correlation

The participant question subject is built in one shared function used by both message construction and manual-send detection:

```text
QOTD - 2026-07-10
```

Replies should be correlated to the stored outbound Gmail message/thread ID when available. Subject and date filtering may be used to retrieve a broad candidate set, but code must apply exact timestamps and sender eligibility before scoring.

Organizer-only messages must use distinct subjects, for example:

```text
QOTD scoring update - 2026-07-09
QOTD scoring skipped - 2026-07-09
QOTD alert - score-responses - 2026-07-10
```

No organizer-only message may satisfy the exact participant-question subject matcher.

## 7. Persistent State

BigQuery is the system of record. GitHub Actions caches and artifacts must not be used as application state.

### 7.1 Questions

Store one logical question per game date with:

- `game_date`;
- prompt;
- exactly four options, `A` through `D`;
- correct option;
- source note and one or more source URLs;
- selected category and topic;
- source type: `generated` or `manual`;
- outbound Gmail message and thread IDs when available;
- creation timestamp.

Writes must be idempotent by game date. A rerun must not create competing questions for the same date.

### 7.2 Monthly scores

Store the current score by normalized participant email and `MMYY` series. Historical monthly buckets must be retained.

### 7.3 Response processing

For each game date and participant, store:

- latest eligible Gmail message ID;
- interpreted option;
- points awarded;
- whether organizer review is required;
- processing timestamp.

The `(game_date, participant_email)` result is idempotent. Reruns must not award duplicate points.

### 7.4 Manual changes

Correct-answer changes and score adjustments must be append-only audit records with their source management-message ID and an idempotency key. Applying an already-seen key must be a no-op.

## 8. Response Collection and Scoring

The answer window begins after the stored question's send time and ends immediately before 7:00 AM Mountain on the scoring date. A reply received at or after the cutoff is late and receives no point.

For each eligible Google Contacts participant:

1. Collect replies belonging to the game question.
2. Select the latest reply before the cutoff.
3. Parse a reply containing only `A`, `B`, `C`, or `D` deterministically and case-insensitively.
4. Send other non-empty replies to the answer interpreter with the question and options.
5. Award one point when the interpreted option matches the stored correct option; otherwise award zero.

The interpreter determines intended choice, not correctness. Humor, commentary, uncertainty, or explanation must not cause `UNKNOWN` when the reply still communicates one clear intended option. It must return `UNKNOWN` and require review only when the participant leaves no discernible selection, selects conflicting choices, or attempts a loophole that materially changes which answer is intended.

The latest eligible reply supersedes earlier replies, including when the later reply changes the participant's answer.

If a manual question has no correct answer, scoring must fail closed for that game date, notify the organizer with the correct-answer template, and remain safely rerunnable.

## 9. Organizer Scoring Update

The weekday organizer-only update must contain:

- previous game day's question and correct answer;
- each participant who answered correctly;
- each participant who answered incorrectly;
- each participant with no eligible reply;
- late replies;
- responses requiring review, including Gmail message IDs and a prefilled adjustment template;
- current standings for every participant in the Google Contacts group;
- monthly winner/reset information when applicable;
- operational warnings.

The update must not be sent to the participant group.

## 10. Question Research and Generation

### 10.1 Simple selection policy

Question selection must remain deliberately simple:

1. Randomly choose one category from the configured category list.
2. Use web search to find candidate trivia topics and supporting sources for that category.
3. Randomly choose one viable topic from the returned candidates.
4. Generate one question from that topic and its source material.
5. Validate the structure deterministically and verify the factual claim against web sources.
6. Retry the whole selection flow only up to a small configured limit. On exhaustion, alert the organizer and do not send.

Random selection may use the game date as a seed so a rerun is reproducible. The MVP must not balance categories using historical frequency, create a multi-stage category-priority plan, or implement entity/topic novelty windows.

`determine_category_order` is therefore not part of the target design. Its responsibilities should be replaced by a small random category/topic selector or folded into the generation use case.

### 10.2 Web-search capability

The use case must depend on an injected interface rather than a concrete vendor:

```python
class WebSearchClient(Protocol):
    def search(self, query: str, *, max_results: int = 5) -> list[WebSearchResult]: ...
```

Each result must provide at least a title, URL, and text snippet. The production adapter may use a supported search API or an OpenAI model with web-search tooling, but tests must use a deterministic fake.

Research rules:

- Prefer primary sources such as government, museum, university, scientific, official organization, or original publisher pages.
- Use reputable secondary sources when no suitable primary source exists.
- Reject inaccessible sources, unsupported claims, volatile facts, and results that do not establish exactly one correct answer.
- Verification must use retrieved source evidence, not the model's memory or an unverified URL generated by the model.
- Store the final supporting URLs with the question.

### 10.3 Generation contract

The model must return structured data containing:

- prompt;
- exactly four distinct options keyed `A`, `B`, `C`, and `D`;
- exactly one correct option;
- source note;
- supporting source URLs;
- category and topic.

The generation prompt must summarize the actionable rules in [docs/qotd_tone_guidelines.md](docs/qotd_tone_guidelines.md). It must describe the desired voice directly and must not use a person's name as shorthand for style.

Deterministic validation must reject missing or duplicate options, invalid correct-option labels, answer leakage, missing sources, invalid HTTP(S) URLs, and empty text. Source verification must reject ambiguity or a correct answer not supported by the retrieved evidence.

Participant-facing email text must be assembled by code from validated structured fields. It must never contain the correct answer, source material, or internal validation notes.

## 11. Manual Operations

### 11.1 Correct answer

For a manually sent question, an approved organizer may submit:

```text
Action: set-correct-answer
Game date: 2026-07-08
Correct option: C
Source URL: https://example.com/source-for-answer
```

The management job must validate sender, date, option, source URL, question existence, and idempotency key, then confirm or reject the request by email.

### 11.2 Score adjustment

An approved organizer may submit:

```text
Action: adjust-score
Participant: person@example.com
Game date: 2026-07-08
Points: 1
Reason: unclear_answer_accepted
Gmail message ID: msg_123
```

The management job must validate the request, apply it idempotently, retain an audit record, and reply with the result. Equivalent local CLI commands must remain available for development and recovery.

### 11.3 Reruns

CLI commands must support dry runs and idempotent reruns for question sending, scoring a specified game date, organizer-update rendering/sending, correct-answer processing, and score adjustments.

## 12. Monthly Cycle

- The final game day is the last weekday of the calendar month in Mountain time.
- Finalization occurs only after that game's 7:00 AM answer cutoff and scoring, normally in the next weekday's organizer update.
- All participants tied for the highest score are winners.
- Winner announcements are organizer-only for the MVP.
- Resetting starts a new monthly score series and never deletes the prior series.

## 13. Failure Handling and Observability

Participant-facing sends fail closed. If participant resolution, manual-send detection, generation, validation, source verification, or Gmail sending fails, the system must not send a question.

Every workflow must emit concise structured logs containing job name, game date, outcome, and identifiers needed for diagnosis. A skipped noon send is a successful, explicit outcome and must log:

- `outcome=skipped`;
- `reason=question_subject_already_exists`;
- exact subject;
- matched Gmail message ID.

Operational failures must notify the organizer with job name, date, summary, and a suggested recovery command. Completed state changes must remain idempotently rerunnable when a later notification step fails.

## 14. Required Tests

Unit and integration-style tests with fake adapters must cover:

- exact dated subject construction and matching;
- scoring updates not matching the participant-question subject;
- manual question detection and explicit skip logging;
- Google Contacts normalization, empty groups, and unknown senders;
- exact cutoff boundaries, Monday/Friday behavior, and Mountain time;
- latest eligible response selection;
- humorous freeform answers with a clear choice;
- ambiguous, conflicting, and loophole answers requiring review;
- random selection reproducibility when seeded;
- web-search result parsing and source preference;
- unsupported or ambiguous factual claims being rejected;
- generation retry exhaustion failing closed;
- scoring and adjustment idempotency;
- final-weekday winner calculation and new-series rollover.

Live-service tests must be optional and must never send participant email by default.

## 15. Implementation Order

1. Centralize participant-question subject construction and exact-match detection.
2. Move runtime prompts into the package and correct their behavioral guidance.
3. Make Google Contacts eligibility consistent across send and score workflows.
4. Replace category ordering and novelty orchestration with random category/topic selection.
5. Add the injected web-search interface, production adapter, and fake test adapter.
6. Generate and verify questions from retrieved evidence.
7. Complete scoring, monthly rollover, alerts, and end-to-end dry-run coverage.
