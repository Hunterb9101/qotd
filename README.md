# Automated Question of The Day

## Context

In high school, a friend of mine ran a daily trivia question via email during our computer science class. It was highly informal and was super enjoyable. However, as we grew older, the question of the day (QOTD) became inconsistent, and eventually died out.

Fast forward a decade, and I realized that we could use AI to automate much of the workflow while keeping the original charm of QOTD alive. While it would have been simpler to automate outright, I added a number of tools to allow my friend to add questions in as he pleases, and AI will pick up the days that he doesn't feel like writing them up.

## Features

### Full Automation via Github Actions

- Automated scoring cutoff at 6 AM PDT
- Scheduled scoring summary sent to the organizer email at 7 AM PDT
- Automated trivia question sent to participants at 2 PM PDT
- Deliver questions through a private Google Group and derive monthly participation from positive scores

### Human-in-the-Loop Controls
- Adjust any participant's score
- AI respects any QOTD email sent out by an organizer.

## Setup

### Email

QOTD uses a Gmail account for sending, reply collection, and organizer controls. Automated participant questions are sent to a private, invitation-only Google Group rather than directly to a blind-copy recipient list. Configure the Group so only the organizer can post, replies go to the original author, conversations and membership are private, and the standard subscription footer is enabled.

Google Group membership is the only participant list. QOTD scores replies correlated to the applicable question and includes only participants with positive points in current-month standings and non-respondent reporting.

We will also be using the google account to access the Google Cloud Platform (GCP).

### OpenAI Developer Account
We'll need an API key to discover topics and generate questions.

### Google Cloud Platform

We'll need to enable the Gmail and BigQuery APIs. The following permissions will be needed via OAuth Access (a service account will only work if you have your own domain):
- `.../auth/bigquery` (Database access)
- `.../auth/gmail.modify` (Add label to manually-sent QOTD emails)
- `.../auth/gmail.readonly` (Score participant responses)
- `.../auth/gmail.send` (Send QOTD)

### Database

Given the small-scale operations and the ephemeral nature of Github Actions, I opted to utilize a BigQuery dataset to manage the state, keeping track of prior asked questions and participant scores. Note that you will need to provide billing (but stay on free tier) to be able to perform DML SQL commands.

### Github Actions

This repository relies heavily on the workflows defined in `.github/workflows`. Create a `production` environment and add the `QOTD_SENDER`, `QOTD_GOOGLE_GROUP_EMAIL`, `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`, `GOOGLE_OAUTH_REFRESH_TOKEN`, and `OPENAI_API_KEY` environment secrets. `QOTD_GOOGLE_GROUP_EMAIL` is the private Group's `@googlegroups.com` address. The three Google OAuth values are determined by `scripts/generate_oauth_refresh_token.py`; sign in with the same organizer email stored in `QOTD_SENDER`. Set `GOOGLE_CLOUD_PROJECT` to the necessary GCP project.

##  For Developers
### Local Installation
Install dependencies in a virtual environment:

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

Production commands use Gmail and BigQuery. Provide these values with environment variables or matching CLI options:

```bash
export GOOGLE_OAUTH_CLIENT_ID="..."
export GOOGLE_OAUTH_CLIENT_SECRET="..."
export GOOGLE_OAUTH_REFRESH_TOKEN="..."
export QOTD_SENDER="organizer@example.com"
export QOTD_GOOGLE_GROUP_EMAIL="your-private-group@googlegroups.com"
export GOOGLE_CLOUD_PROJECT="..."
export BIGQUERY_DATASET="qotd"
export OPENAI_API_KEY="..."
```

Scoring uses OpenAI to interpret freeform replies that are not a plain `A`, `B`, `C`, or `D`. Use `OPENAI_INTERPRETER_MODEL` to override the default interpreter model. For local deterministic-only scoring, pass `--disable-ai-answer-interpreter`.

## Developer AI Tools

Generate several question candidates for a topic without sending email or reading or writing production state:

```bash
python -m qotd generate-samples --topic "cheese history" --count 3
```

The command requires `OPENAI_API_KEY`, uses `OPENAI_GENERATOR_MODEL` when set, and lets the generator research each candidate with web search. Samples choose from the defined trivia categories without repeating a category until the set is exhausted; pass `--category` to use one category for the whole batch. The command prints structured JSON containing each question, four options, its correct option, and source metadata.

Run the offline test suite with:

```bash
pytest tests/
```

Live answer-interpreter evaluations live in the mirrored `tests/usecases/test_score_responses.py` module, carry the `intg` pytest marker, and only run when selected explicitly:

```bash
OPENAI_API_KEY="..." pytest -m intg
```

Use `OPENAI_INTERPRETER_MODEL` to select the live evaluation model. Explicit integration runs fail with a configuration error when `OPENAI_API_KEY` is missing.

### Email Management Jobs

The GitHub Actions workflow `.github/workflows/qotd-score-adjustments.yml` runs management email processing at `13:55 UTC` on weekdays, five minutes before the QOTD scoring workflow. It processes correct-answer requests first, then score-adjustment requests. It shares a concurrency group with the scoring workflow so state writes do not overlap.

### Correct Answer Emails

When a manual email is sent, send a correct-answer email before scoring:

```text
Action: set-correct-answer
Game date: 2026-07-08
Correct option: C
Source URL: https://example.com/source-for-answer
```

The management job validates the approved organizer sender, stored question date, option, source URL, and idempotency key. If a manual question is missing its correct answer, scoring skips that game date and sends the organizer the expected template.

Run manually with:

```bash
python -m qotd process-correct-answers \
  --organizer organizer@example.com
```

### Email Score Adjustments

The intended organizer workflow is email-based. Send a plain-text request to the QOTD admin mailbox:

```text
Action: adjust-score
Participant: person@example.com
Game date: 2026-07-08
Points: 1
Reason: unclear_answer_accepted
Gmail message ID: msg_123
```

Then run the management job:

```bash
python -m qotd process-score-adjustments \
  --organizer organizer@example.com
```

The command searches unread Gmail messages matching `Action: adjust-score`, accepts requests only from approved organizer addresses, applies valid adjustments, sends the requester a confirmation or rejection email, and removes the unread label from handled requests.

Use `Month: 2026-07` or `Series: 0726` instead of `Game date` for month-level corrections:

```text
Action: adjust-score
Participant: person@example.com
Month: 2026-07
Points: -1
Reason: duplicate_correction
```

Preview processing without writing scores or sending responses:

```bash
python -m qotd process-score-adjustments \
  --organizer organizer@example.com \
  --dry-run
```

### Local Score Adjustments

Use `adjust-score` only for development or emergency corrections when email processing is not appropriate.

```bash
python -m qotd adjust-score \
  --email person@example.com \
  --date 2026-07-08 \
  --points 1 \
  --reason unclear_answer_accepted \
  --gmail-message-id msg_123
```

The command:

- converts `--date` into the monthly score series, such as `0726`;
- requires a stored question record for date-based adjustments;
- appends a `manual_adjustments` audit record;
- appends a new `monthly_scores` total for the participant;
- skips duplicate adjustments with the same idempotency key.

For an adjustment that is tied to a whole month instead of one game date, use the `MMYY` score series:

```bash
python -m qotd adjust-score \
  --email person@example.com \
  --series 0726 \
  --points -1 \
  --reason duplicate_correction
```

Common reasons are `organizer_override`, `unclear_answer_accepted`, `incorrect_auto_score`, and `duplicate_correction`.

By default, the idempotency key is:

```text
manual:{date-or-series}:{participant-email}:{reason}
```

Provide `--idempotency-key` when applying multiple distinct adjustments with the same participant, date or series, and reason:

```bash
python -m qotd adjust-score \
  --email person@example.com \
  --date 2026-07-08 \
  --points 1 \
  --reason organizer_override \
  --idempotency-key manual:2026-07-08:person@example.com:organizer_override:second
```

Preview an adjustment without writing to BigQuery:

```bash
python -m qotd adjust-score \
  --email person@example.com \
  --date 2026-07-08 \
  --points 1 \
  --reason unclear_answer_accepted \
  --dry-run
```

### Manual Scoring Reruns

Rerun scoring for a specific game date with:

```bash
python -m qotd score-responses --game-date 2026-07-08
```

Use `--dry-run` to fetch replies and render the organizer update body without sending the organizer email.
