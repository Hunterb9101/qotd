# Automated Question of the Day

QOTD is an email-based trivia game that keeps itself running while leaving room for a human organizer to step in whenever inspiration strikes.

## The Story

In high school, a friend of mine ran a daily trivia question by email during our computer science class. It was informal, inconsistent, and extremely fun. Over time, though, the questions became less frequent and eventually stopped.

A decade later, this project uses AI to keep that tradition alive. An organizer can still write and send a question manually; on days they do not, QOTD generates and delivers one automatically.

## What It Does

- Sends a weekday trivia question to a private Google Group.
- Collects replies and scores participant answers.
- Uses AI to understand freeform answers when needed.
- Emails the organizer a scoring summary.
- Tracks monthly participation and scores in BigQuery.
- Lets the organizer correct answers and adjust scores by email.
- Respects questions sent manually by the organizer.

The recurring jobs run through GitHub Actions. Gmail handles delivery and replies, Google Group membership defines the participants, BigQuery stores game state, and OpenAI generates questions and interprets freeform answers.

## Get Started

- [For operators](docs/for-operators.md): configure the production service, run the daily game, and handle corrections.
- [For developers](docs/for-developers.md): install the project locally, generate sample questions, and run tests.

## More Documentation

- [Architecture Decision Records](docs/adr/)
- [Project Requirement Docs](docs/prd/)
- [Tone guidelines](docs/qotd_tone_guidelines.md)
- [User journeys](docs/user-journeys.md)
