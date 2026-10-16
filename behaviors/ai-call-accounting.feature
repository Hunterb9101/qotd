@ai-call-accounting
Feature: Account for AI Calls
  QOTD retains the provider usage metadata needed to estimate the cost of each
  AI Call without interrupting the workflow that made it.

  Scenario: A Question research call uses web search
    Given an AI provider returns token usage and one web-search tool call
    When QOTD records the resulting AI Call
    Then the AI Call includes the input, cached-input, output, and total token counts
    And the AI Call records one web-search call
