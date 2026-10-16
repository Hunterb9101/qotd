@workflow-isolation
Feature: Isolate email workflows and preserve auditability
  Player Submissions and Organizer Instructions have separate contracts.

  Scenario: Process a Player Submission only as a Submission
    Given a Player replies to a published Question
    When the scoring workflow runs
    Then it records and evaluates the reply as a Submission
    And it does not create an Organizer Instruction outcome from that reply

  Scenario: Process an approved Organizer Instruction only in its workflow
    Given an approved Organizer sends a valid manual Score Event instruction
    When the Organizer Instruction workflow runs
    Then it records one immutable manual Score Event linked to that instruction
    And it reports the resulting Score and event identity to the Organizer
    And it leaves Player Submissions for the scoring workflow

  Scenario: Reject or deduplicate an Organizer Instruction safely
    Given an Organizer Instruction is invalid, conflicting, or a duplicate
    When it is processed
    Then it has one durable outcome: rejected, applied, or duplicate
    And a rejected or outcome email is never processed as a future instruction

  Scenario: Collect late Submissions without rescoring
    Given a published Game is in the current or immediately preceding Series
    When a later collection pass finds a previously unseen late Submission
    Then it stores the Submission with the late ineligibility reason
    And it does not create or change automatic Score Events for a scored Game
