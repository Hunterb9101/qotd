# QOTD Game Lifecycle and State Journeys (Draft)

## Purpose

This document describes [**QOTD**](DEFINITIONS.md#qotd) as a sequence of [**Game**](DEFINITIONS.md#game)
cycles, from preparing a [**Question**](DEFINITIONS.md#question) through scoring and
corrections. It is intentionally a product and
state-transition draft, not a database schema. The write tables and their
constraints should be derived from these journeys after the behaviors are
agreed.

## Lifecycle Overview

[**Create and publish a Game**](DEFINITIONS.md#game)

Automated path | manual path

↓

[**Collect Player Submissions**](DEFINITIONS.md#submission)

↓

[**Close and score the Game**](DEFINITIONS.md#game)

↓

Correct or recover when needed

↓

Display results and begin the next [**Game**](DEFINITIONS.md#game)

The phases describe the normal path. Validation failures and retries belong to
the phase where they occur; they must not create competing [**Game**](DEFINITIONS.md#game),
[**Answer**](DEFINITIONS.md#answer), or [**Score**](DEFINITIONS.md#score) state.

## 1. Create and Publish a Game

### 1.1 Automated path

**Trigger:** the scheduled [**Question**](DEFINITIONS.md#question)-publication workflow starts for a [**Day**](DEFINITIONS.md#day)
with no accepted [**Organizer Instruction**](DEFINITIONS.md#organizer-instruction) that
results in a valid manual [**Question**](DEFINITIONS.md#question).

1. Remove any pending [**Answer**](DEFINITIONS.md#answer) for the [**Day**](DEFINITIONS.md#day).
2. Generate and validate a [**Question**](DEFINITIONS.md#question).
3. Publish the [**Question**](DEFINITIONS.md#question) to [**Players**](DEFINITIONS.md#player).
4. Record the published [**Game**](DEFINITIONS.md#game) and the outbound Gmail message identity.

**Retry rule:** publication is idempotent for a [**Day**](DEFINITIONS.md#day).

### 1.2 Manual path

**Trigger:** an [**Organizer**](DEFINITIONS.md#organizer) sends an
[**Organizer Instruction**](DEFINITIONS.md#organizer-instruction) to publish a manual
[**Player**](DEFINITIONS.md#player) [**Question**](DEFINITIONS.md#question).

There are two valid orders:

1. The [**Organizer**](DEFINITIONS.md#organizer) may first send an
   [**Organizer Instruction**](DEFINITIONS.md#organizer-instruction) that sets an
   [**Answer**](DEFINITIONS.md#answer) for a future [**Day**](DEFINITIONS.md#day). The system
   records a pending [**Game**](DEFINITIONS.md#game) with that [**Answer**](DEFINITIONS.md#answer).
2. The [**Organizer**](DEFINITIONS.md#organizer) publishes the manually composed
   [**Player**](DEFINITIONS.md#player) [**Question**](DEFINITIONS.md#question) using the required dated
   subject. The system detects or is told about that published message, captures the
   [**Question**](DEFINITIONS.md#question), and publishes the [**Game**](DEFINITIONS.md#game).

The system associates a pending [**Answer**](DEFINITIONS.md#answer) with the published manual
[**Game**](DEFINITIONS.md#game). If there is no pending [**Answer**](DEFINITIONS.md#answer), the [**Organizer**](DEFINITIONS.md#organizer)
may send an [**Organizer Instruction**](DEFINITIONS.md#organizer-instruction) that sets it at
any time before the following [**Day**](DEFINITIONS.md#day)'s scoring workflow.

**Validation:** a pending [**Answer**](DEFINITIONS.md#answer) must be for a valid
[**Day**](DEFINITIONS.md#day) and contain one of the allowed option labels. Once the
manual [**Question**](DEFINITIONS.md#question) is available, the option must be valid for
that [**Question**](DEFINITIONS.md#question). A second, conflicting [**Answer**](DEFINITIONS.md#answer)
must be rejected rather than stored as another candidate.

**Retry rule:** manual publication detection is idempotent by Gmail message identity.

## 2. Collect Player Submissions

**Trigger:** [**Player**](DEFINITIONS.md#player) [**Submissions**](DEFINITIONS.md#submission)
arrive for a published [**Question**](DEFINITIONS.md#question).

1. Associate every [**Submission**](DEFINITIONS.md#submission) with the published
   [**Game**](DEFINITIONS.md#game) using its message/thread identity and dated subject,
   regardless of eligibility.
2. Normalize the [**Player**](DEFINITIONS.md#player) email address.
3. Record each [**Submission**](DEFINITIONS.md#submission)'s eligibility status and, when it is ineligible,
   its [**Ineligibility Reason**](DEFINITIONS.md#ineligibility-reason).
4. For each [**Player**](DEFINITIONS.md#player), determine the latest eligible
   [**Submission**](DEFINITIONS.md#submission) before scoring.

**Retry rule:** [**Submission**](DEFINITIONS.md#submission) collection is idempotent by Gmail message identity.

## 3. Close and Score the Game

**Trigger:** the scheduled scoring workflow reaches the [**Game**](DEFINITIONS.md#game)’s
[**Deadline**](DEFINITIONS.md#deadline), or an [**Organizer**](DEFINITIONS.md#organizer) intentionally reruns scoring
for a [**Day**](DEFINITIONS.md#day).

1. Confirm that the [**Game**](DEFINITIONS.md#game) was published and has exactly one
   [**Answer**](DEFINITIONS.md#answer).
2. If the [**Answer**](DEFINITIONS.md#answer) is missing, do not score the [**Game**](DEFINITIONS.md#game).
   Send the [**Organizer**](DEFINITIONS.md#organizer) a scoring update that identifies the
   unscored [**Day**](DEFINITIONS.md#day), states that no [**Answer**](DEFINITIONS.md#answer) was set, and directs the
   [**Organizer**](DEFINITIONS.md#organizer) to set the [**Answer**](DEFINITIONS.md#answer) and use a manual GHA scoring run to score the [**Game**](DEFINITIONS.md#game).
3. Freeze the selection of eligible [**Submissions**](DEFINITIONS.md#submission) for this scoring run.
4. Interpret each [**Player**](DEFINITIONS.md#player)'s [**Submission**](DEFINITIONS.md#submission) and determine its
   [**Score Event**](DEFINITIONS.md#score-event) delta.
5. Write an immutable [**Score Event**](DEFINITIONS.md#score-event) for each awarded point or
   explicit zero-point outcome, linked to the [**Game**](DEFINITIONS.md#game) and [**Submission**](DEFINITIONS.md#submission)
   that caused it.
6. Mark the [**Game**](DEFINITIONS.md#game) scored and notify the [**Organizer**](DEFINITIONS.md#organizer).

**Retry rule:** scoring is idempotent by [**Score Event**](DEFINITIONS.md#score-event) identity.

## 4. Correct or Recover

This phase contains exceptional [**Organizer Instructions**](DEFINITIONS.md#organizer-instruction)
and recovery actions after a [**Game**](DEFINITIONS.md#game) is prepared, published, or scored.
Each Organizer Instruction has an idempotency identity and an observable outcome.

### 4.1 Manual Score Event

**Trigger:** an approved [**Organizer**](DEFINITIONS.md#organizer) sends an
[**Organizer Instruction**](DEFINITIONS.md#organizer-instruction) that creates a manual
[**Score Event**](DEFINITIONS.md#score-event).

Only an approved [**Organizer Instruction**](DEFINITIONS.md#organizer-instruction)
may trigger a Manual Score Event outcome. [**Player**](DEFINITIONS.md#player)
[**Submissions**](DEFINITIONS.md#submission) and messages from non-Organizers are
outside this workflow: they receive no outcome, remain unread, and are left for
Submission processing.

1. Record receipt of the [**Organizer Instruction**](DEFINITIONS.md#organizer-instruction) and
   validate its sender and fields.
2. Resolve the targeted [**Player**](DEFINITIONS.md#player) and either [**Game**](DEFINITIONS.md#game)
   [**Day**](DEFINITIONS.md#day) or [**Series**](DEFINITIONS.md#series), then validate the requested delta.
3. Write one immutable manual [**Score Event**](DEFINITIONS.md#score-event) linked to the
   [**Organizer Instruction**](DEFINITIONS.md#organizer-instruction).
4. Report the resulting [**Score**](DEFINITIONS.md#score) and the event identity to
   the [**Organizer**](DEFINITIONS.md#organizer).

A manual [**Score Event**](DEFINITIONS.md#score-event) may apply to a [**Player**](DEFINITIONS.md#player)
who has no earlier Score Event. Their [**Score**](DEFINITIONS.md#score) begins at zero plus
that event's delta.

### 4.2 Invalid, duplicate, or conflicting commands

Every [**Organizer Instruction**](DEFINITIONS.md#organizer-instruction) email must have one
recorded processing outcome:

- accepted and applied;
- accepted but skipped as an idempotent duplicate; or
- rejected with a stable reason.

The parser must operate only on the [**Organizer Instruction**](DEFINITIONS.md#organizer-instruction)
payload, not quoted history or examples included in a response template. A
rejected [**Organizer Instruction**](DEFINITIONS.md#organizer-instruction) and its confirmation or rejection message must
never become a future [**Organizer Instruction**](DEFINITIONS.md#organizer-instruction).

### 4.3 Failed or partial workflows

If [**Question**](DEFINITIONS.md#question) publication or persistence fails, the next run must be able to inspect
the [**Game**](DEFINITIONS.md#game) and [**Organizer Instruction**](DEFINITIONS.md#organizer-instruction) state
and determine whether to resume or safely stop.
It must not infer completion merely from a timestamped snapshot. Every external
side effect, especially a published [**Question**](DEFINITIONS.md#question), needs a durable identity that can be
reconciled with the recorded [**Game**](DEFINITIONS.md#game) state.

## 5. Display Results and Roll Forward

**Trigger:** the automated workflow publishes the following [**Day**](DEFINITIONS.md#day)'s
[**Question**](DEFINITIONS.md#question) after a [**Game**](DEFINITIONS.md#game) is scored.
It packages the prior [**Game**](DEFINITIONS.md#game)'s [**Scoreboard**](DEFINITIONS.md#scoreboard) and
[**Answer**](DEFINITIONS.md#answer) with that publication. A manually published
[**Question**](DEFINITIONS.md#question) does not guarantee that results are packaged or sent.

1. Read the current [**Scoreboard**](DEFINITIONS.md#scoreboard) and the prior
   [**Game**](DEFINITIONS.md#game)'s [**Answer**](DEFINITIONS.md#answer).
2. Render and send the required [**Player**](DEFINITIONS.md#player)-facing or
   [**Organizer**](DEFINITIONS.md#organizer)-facing message.

This phase is read-only. It must not mutate [**Game**](DEFINITIONS.md#game) or
[**Score Event**](DEFINITIONS.md#score-event) state.
