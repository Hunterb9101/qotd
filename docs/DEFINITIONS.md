# QOTD Definitions

This document is the source of truth for terminology used in QOTD design,
implementation, documentation, and operational workflows. Existing code and
documentation may use inconsistent or legacy terminology; new work should use
the terms defined here.

## Contributing Terms

Before introducing a new term, check whether an existing definition already
expresses the same concept. If a new term is needed:

1. Choose the existing `###` category that best fits it; add a category only
   when none fit.
2. Add a `####` heading with a short, unambiguous definition.
3. Link to other defined terms used in its definition.
4. Update affected documentation to use and link to the new term.
5. Avoid adding synonyms for an existing term; revise the existing definition
   instead when the concept is the same.

## Terms

### Foundation

#### QOTD

Question of the Day, the daily multiple-choice trivia game.

#### Day

The calendar day in the `America/Denver` timezone. A Day identifies the date
of a [**Game**](#game) and governs its scheduled workflow times.

#### AI Call

An append-only durable record of one request sent to an AI provider and its
result. An AI Call records its [**Use Case Run**](#use-case-run), prompt,
provider request and response (without credentials), provider and model,
status or error, and available timing and usage metadata.

#### Use Case Run

One execution of a top-level workflow, identified by a run identifier shared
only by the [**AI Calls**](#ai-call) caused by that execution. It is not a
cross-workflow or lifecycle-wide trace identifier.

### Roles

#### Player

An individual who competes in [**QOTD**](#qotd) by receiving
[**Questions**](#question) and making [**Submissions**](#submission).

A [**Player**](#player) is **active** in a [**Series**](#series) when they have
made at least one [**Submission**](#submission) during that Series. Activity is
independent of [**Score**](#score), so an active Player may have a zero or
negative Score.

#### Organizer

An individual authorized to prepare [**Games**](#game) and submit
[**Organizer Instructions**](#organizer-instruction).

### Scoring and Series

#### Series

A predetermined set of [**Games**](#game) over a time period, used to determine
a winner. A **Series** currently spans one calendar month.

#### Winner

The [**Player**](#player) with the highest [**Score**](#score) at the end of a
[**Series**](#series). Tie handling is a [**Series**](#series) rule that must
be specified before a Winner is determined.

#### Score

A [**Player**](#player)’s total points within a [**Series**](#series),
calculated from all [**Score Events**](#score-event) that apply to that
[**Series**](#series).

#### Score Event

An immutable record of a specified positive, zero, or negative point delta that
contributes to a [**Player**](#player)’s [**Score**](#score) in a
[**Series**](#series). It records its cause and source identity, such as the
outcome of a [**Player**](#player)’s response to a [**Game**](#game) or an
[**Organizer Instruction**](#organizer-instruction), so that the
[**Score**](#score) can be audited and safely retried.

#### Scoreboard

The ordered view of each [**Player**](#player) with a [**Submission**](#submission)
or [**Score Event**](#score-event) in the current [**Series**](#series), showing
their current [**Score**](#score). It is sent alongside each [**Question**](#question).

### Game Lifecycle

#### Game

The [**QOTD**](#qotd) for a given [**Day**](#day). A **Game** is either
**pending** (only for a manual workflow) or **published** to
[**Players**](#player), with its Player-facing delivery tracked by an associated
[**Outbound Message**](#outbound-message). A published [**Game**](#game) becomes **scored** when its eligible
[**Submissions**](#submission) have produced their automatic
[**Score Events**](#score-event). A [**Game**](#game) may be scored only once;
later corrections use separate [**Score Events**](#score-event).

#### Outbound Message

A durable intent to send a [**Player**](#player)- or
[**Organizer**](#organizer)-facing email caused by a [**Game**](#game)
transition or [**Organizer Instruction**](#organizer-instruction). It is
**pending** until it is sent or uniquely reconciled with Gmail, then records
the one-way Gmail message identity and send time as **sent**. A pending
**Outbound Message** must be reconciled with Gmail before a retry; if it cannot
be uniquely identified, it remains pending and fails closed.

#### Question

The [**Player**](#player)-facing prompt, exactly four multiple-choice options
labeled `A` through `D`, one [**Answer**](#answer), and source information
supporting that [**Answer**](#answer).

#### Answer

The selected option and source information that scoring uses for a
[**Game**](#game). It may be pending before a manual [**Question**](#question)
is published.

#### Deadline

The time after which a [**Submission**](#submission) is no longer eligible for
a [**Question**](#question).

#### Submission

A [**Player**](#player)’s response to a [**Question**](#question). A
[**Submission**](#submission) is eligible only when it is received before that
[**Question**](#question)’s [**Deadline**](#deadline) and it either selects an
option from `A` through `D` or makes a loophole case for
an answer outside the multiple-choice options; a loophole case earns points
only at the [**Organizer**](#organizer)’s discretion. A [**Player**](#player)
may make multiple [**Submissions**](#submission) for a [**Game**](#game);
scoring selects the latest eligible Submission.

Use **Submission** only for a [**Player**](#player)’s response. An
[**Organizer**](#organizer) sends an
[**Organizer Instruction**](#organizer-instruction); an Organizer does not
submit an [**Answer**](#answer).

#### Ineligibility Reason

The recorded reason a [**Submission**](#submission) is not used for scoring.

- **superseded:** A later eligible Submission from the same [**Player**](#player)
  for the same [**Game**](#game) is selected for scoring.
- **late:** The Submission was received at or after the
  [**Question**](#question)'s [**Deadline**](#deadline). A late Submission does
  not supersede an earlier eligible Submission.

### Organizer Workflow

#### Organizer Instruction

A structured email action sent by an approved [**Organizer**](#organizer).
An **Organizer Instruction** may create a [**Score Event**](#score-event), set
an [**Answer**](#answer), or add a [**Question**](#question).
