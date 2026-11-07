@monthly-series
Feature: Complete a monthly Series
  QOTD recognizes Winners and begins the next Series without carrying scores forward.

  Scenario: Announce every tied Winner on the final weekday
    Given the final weekday Game of a calendar month has been scored
    When the next Game is published
    Then it announces every Player tied for the highest Score as a Winner
    And it does not announce Players below the highest Score

  Scenario: Start the next Series with a new Scoreboard
    Given the prior monthly Series is complete
    When the first Game of the next month is published
    Then that Game belongs to a new Series
    And the new Series Scoreboard is empty until a Player has a Submission or Score Event

  Scenario: Show all active Players in a Series Scoreboard
    Given a Player has a Submission or Score Event in a Series
    When the Scoreboard is read
    Then it includes that Player even when the Player's Score is zero or negative
