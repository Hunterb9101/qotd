@ai-call-usage
Feature: Record AI Call token usage
  QOTD preserves available AI Call usage metadata without interrupting a
  Question publication.

  Scenario: Provider returns token counts as strings
    Given an AI provider returns decimal-string token counts with a successful response
    When QOTD records the resulting AI Call
    Then it records whole-number token usage
    And the successful response remains available to the publication workflow
