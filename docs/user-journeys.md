# QOTD User Journeys

This document is a quick starting point for understanding the main product outcomes and the use cases involved. The PRD defines required behavior, and the technical specification provides implementation detail.

## Automated weekday question

**Outcome:** Participants receive one generated QOTD email when the organizer has not already sent a question for the day.

**Primary use cases:**

- [`send_question`](../qotd/usecases/send_question.py) coordinates the daily check and automated send.
- [`check_manual_question`](../qotd/usecases/check_manual_question.py) checks whether the organizer already sent a question.
- [`discover_question_topic_from_web`](../qotd/usecases/discover_question_topic_from_web.py) selects a web-informed topic direction.
- [`generate_question_for_topic`](../qotd/usecases/generate_question_for_topic.py) generates and validates the question.
- [`repair_generated_question`](../qotd/usecases/repair_generated_question.py) makes focused corrections when a candidate is rejected.

## Organizer sends the question

**Outcome:** The organizer's QOTD is recognized as the day's question, stored for later scoring, and automation does not send a duplicate.

**Primary use cases:**

- [`send_question`](../qotd/usecases/send_question.py)
- [`check_manual_question`](../qotd/usecases/check_manual_question.py)
- [`correct_answer`](../qotd/usecases/correct_answer.py) records the answer needed to score the manual question.

## Morning scoring

**Outcome:** Eligible replies are interpreted and scored, monthly standings are updated, and the organizer receives a scoring summary.

**Primary use cases:**

- [`score_responses`](../qotd/usecases/score_responses.py)
- [`question_history`](../qotd/usecases/question_history.py)
- [`score_history`](../qotd/usecases/score_history.py)

## Organizer corrects a score

**Outcome:** An approved correction updates a participant's monthly score without applying the same adjustment twice.

**Primary use case:**

- [`adjust_score`](../qotd/usecases/adjust_score.py)

## Monthly winner and rollover

**Outcome:** All participants tied for the highest monthly score are announced, and the next month's competition begins with separate standings.

**Primary use cases:**

- [`score_responses`](../qotd/usecases/score_responses.py) calculates the final standings and winners.
- [`send_question`](../qotd/usecases/send_question.py) includes the completed-month recap in the next available weekday question.
- [`score_history`](../qotd/usecases/score_history.py) reads scores from the applicable monthly series.
