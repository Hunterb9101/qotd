@daily-game-cycle
Feature: Run an automated daily Game
  QOTD runs a weekday email game without routine Organizer work.

  Scenario: Publish a generated Question to the private Group
    Given no manual Question has been published for a weekday Day
    When the scheduled publication workflow runs at noon Mountain time
    Then it sends one generated Question to the configured private Google Group
    And the message includes exactly four distinct options labeled A through D
    And the message does not expose the Answer
    And the Question has exactly one unambiguous Answer with source information

  Scenario: Score the latest eligible Submission from each Player
    Given a published Game has an Answer and a 7:00 AM Mountain Deadline
    When scoring collects correlated Player Submissions
    Then it retains every Submission for audit
    And it selects each Player's latest Submission received before the Deadline
    And it interprets freeform answers when necessary
    And it creates immutable Score Events for the resulting outcomes
    And a Submission received at or after the Deadline does not affect scoring

  Scenario: Give the Organizer a scoring update and Players a recap
    Given a Game has been scored
    When the Organizer update is rendered
    Then it includes the Answer, correct Players, current Scoreboard, and answers needing review
    When the next automated Question is published
    Then its message includes the prior Answer and current Scoreboard without changing scored state
