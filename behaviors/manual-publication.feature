@manual-publication @outbound-recovery
Feature: Respect manual publication and recover outbound delivery
  An Organizer can take over a Game without duplicate publication or delivery.

  Scenario: A manual Question suppresses generated publication
    Given the Organizer has sent a valid dated Question for a Day
    When the scheduled publication workflow runs for that Day
    Then it records the Game as manually published
    And it does not generate or send another Question

  Scenario: An uncertain email delivery is reconciled before retrying
    Given a state transition has created one durable Outbound Message intent
    And the send outcome is uncertain
    When the workflow retries
    Then it reconciles the persisted recipient, subject, body, and send window with Gmail
    And it marks the intent sent when the message is found
    And it does not send a duplicate when delivery cannot be established

  Scenario: Every external email has a durable, idempotent intent
    Given a state transition requires an external email
    When the transition commits
    Then it persists one Outbound Message intent in the same transaction
    And retries use the same idempotency identity
