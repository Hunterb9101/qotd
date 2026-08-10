# QOTD PRD

## Governing Terminology and State

[QOTD Definitions](../DEFINITIONS.md) is the source of truth for QOTD
terminology, and [ADR-004](../adr/adr-004-canonical-state-model.md) is the
source of truth for canonical state and Scoreboard semantics. Per
[ADR-002](../adr/adr-002-game-lifecycle-and-terminology.md), where this PRD
conflicts with either source, the Definitions and ADR-004 take precedence.

## 1. Summary
- 1.1 The QOTD product will automate the organizer workflow for running a weekday email-based Question of the Day game.
- 1.2 The system will collect Player email replies, use AI to interpret freeform answers, score responses against the previous day's question, send an organizer-only scoring update, generate a new QOTD-style multiple-choice question with exactly four options, and send the next QOTD email only when the organizer has not already sent one that day.
- 1.3 The MVP will support monthly Series by crowning all top-scoring Players on the final game day of each month and starting a new Series for the next month.
- 1.4 The MVP will rely on a private organizer-managed Google Group rather than an application interface for Player management.

## 2. Problem
- 2.1 Running QOTD manually requires the organizer to repeatedly write questions, send emails, collect replies, interpret answers, update scores, and manage monthly resets.
- 2.2 The time and attention required for routine QOTD operations make the game difficult to run consistently over time.
- 2.3 Manual operation creates avoidable risk that weekday questions, answer scoring, point updates, or monthly winner announcements are delayed, skipped, or handled inconsistently.
- 2.4 The MVP should reduce the organizer's routine daily workload while preserving organizer visibility and the core email-based game experience for Players.

## 3. Goals
- 3.1 The system will reduce routine organizer work for the weekday QOTD game while preserving organizer visibility before the next question is sent.
- 3.2 The system will reliably collect, interpret, score, and report Player answers for each weekday game cycle.
- 3.3 The system will generate QOTD-style questions that are suitable to send automatically, with exactly one correct answer and exactly four multiple-choice options.
- 3.4 The system will make the prior game day's Answer, scoring outcome, current Scoreboard, and any suspicious non-A/B/C/D answers visible to the Organizer in a morning scoring update.
- 3.5 The system will complete each monthly Series by announcing all top-scoring Winners and starting the next Series.

## 4. Non-Goals
- 4.1 The MVP will not include a web application, admin UI, or Player self-service interface.
- 4.2 The MVP will not require organizer approval or review before generated questions are sent when no organizer-sent QOTD email has already been detected that day.
- 4.3 The MVP will not support weekend QOTD games.
- 4.4 The MVP will not include tie-breaker rounds or special handling for tied monthly winners.
- 4.5 The MVP will not include Player lifecycle management beyond managing private Google Group membership.
- 4.6 The MVP will not attempt to replace a future organizer oversight workflow beyond providing a basic way to manually adjust scoring when needed.

## 5. Personas
- 5.1 The organizer owns initial setup, private Google Group membership, occasional manual scoring adjustments, and review of the morning scoring update, but does not need to perform routine daily scoring from scratch.
- 5.2 The Organizer needs the game to run consistently on weekdays without needing to write Questions, send emails, score replies, or start a new monthly Series by hand.
- 5.3 Players receive QOTD emails, answer by replying to email, and expect their eligible responses to be scored fairly.
- 5.4 Players rely on QOTD emails to receive new Questions, while the Organizer relies on the scoring update to understand the previous game day's Answer, scoring outcome, current Scoreboard, and Submissions needing review.

## 6. Requirements
- 6.1 The system will send an organizer-only scoring update every weekday at 8:00 AM Mountain time.
- 6.2 The system will stop accepting answers for the previous game day at 7:00 AM Mountain time.
- 6.3 The system will score replies correlated to the applicable QOTD email without requiring a separate Player roster.
- 6.4 The system will treat the latest eligible response from each Player as that Player's answer for the previous game day.
- 6.5 The system will use AI to interpret freeform Player replies and extract the intended multiple-choice answer when the reply contains more than a single answer character.
- 6.6 The system will ignore late responses for scoring purposes.
- 6.7 The system will award one point for each correct eligible response.
- 6.8 The system will generate each new QOTD question from scratch in the historical QOTD style described in [qotd_tone_guidelines.md](qotd_tone_guidelines.md).
- 6.9 Each generated QOTD question will be multiple choice with exactly four answer options.
- 6.10 Each generated QOTD question will have exactly one unambiguous correct answer.
- 6.11 Each generated QOTD question will have no repeated answer options.
- 6.12 The organizer-only scoring update will include the previous game day's correct answer.
- 6.13 The organizer-only scoring update will show which Players answered the previous question correctly.
- 6.14 The Organizer-only scoring update will include the current Series Scoreboard and each Player's Score, including zero and negative Scores for Players with a Submission or Score Event in that Series.
- 6.15 The organizer-only scoring update will highlight responses that do not clearly answer A, B, C, or D for organizer review.
- 6.16 The system will check whether the organizer has already sent a QOTD email that day before sending a generated QOTD email.
- 6.17 If the organizer has not already sent a QOTD email that day, the system will send one generated QOTD email at 12:00 PM Mountain time.
- 6.18 If the organizer has already sent a QOTD email that day, the system will not send a generated QOTD email.
- 6.19 Each generated QOTD email will include the new question and its four answer options without exposing the correct answer.
- 6.20 On the final weekday Game Day of each calendar month, the system will announce all Players tied for the highest Score as monthly Winners.
- 6.21 After announcing monthly Winners, the system will start the next monthly Series.
- 6.22 The system will provide a basic way for an Organizer to create a manual Score Event when needed.
- 6.23 The system will alert the organizer if answer collection, scoring, question generation, or email sending fails.
- 6.24 The system will identify non-respondents only among Players on the current Series Scoreboard.
- 6.25 The Scoreboard will include each Player with a Submission or Score Event in the current Series, including Players with zero or negative Scores.

## 7. Success Metrics
- 7.1 The MVP will be considered successful when it completes a full calendar-month test run of weekday QOTD cycles.
- 7.2 During the test month, every weekday organizer scoring update will be sent at 8:00 AM Mountain without routine organizer intervention.
- 7.3 During the test month, correlated Player Submissions will be collected, interpreted, scored, and reflected in the Organizer scoring update.
- 7.4 During the test month, generated questions will consistently meet the required multiple-choice structure and historical QOTD tone requirements described in [qotd_tone_guidelines.md](qotd_tone_guidelines.md).
- 7.5 During the test month, each Organizer scoring update will correctly report the previous Game Day's Answer, correct Players, the current Scoreboard (including zero and negative Scores where applicable), and Submissions needing review.
- 7.6 During the test month, generated QOTD emails will be sent at 12:00 PM Mountain only on weekdays when the organizer has not already sent a QOTD email.
- 7.7 At the end of the test month, the system will announce all top-scoring monthly Winners and start the next monthly Series.
- 7.8 Any operational failure during the test month will notify the organizer clearly enough to support manual recovery.
