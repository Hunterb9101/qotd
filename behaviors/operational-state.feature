@operational-state
Feature: Maintain canonical operational state
  QOTD state transitions remain auditable and correct when workflows overlap or retry.

  Scenario: Apply a state transition transactionally
    Given a workflow changes Game state and creates related Score Events or Outbound Messages
    When it applies the transition
    Then it validates and writes the related state in one parameterized BigQuery transaction
    And it commits before performing an external side effect

  Scenario: Retry without creating competing state
    Given a workflow action or source message has an idempotency identity
    When that workflow retries after a conflict or partial failure
    Then it reuses the same identity
    And it does not create a competing Game, Answer, Score Event, Submission, or Outbound Message

  Scenario: Preserve the source of each Score Event
    Given a Score Event is recorded
    When its audit trail is read
    Then an automatic Score Event identifies its Game and Submission
    And a manual Score Event identifies its Organizer Instruction
