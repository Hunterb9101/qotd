# QOTD Automation

Command-line workflows for generating, scoring, and manually correcting QOTD scores.

## Setup

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
export GOOGLE_CLOUD_PROJECT="..."
export BIGQUERY_DATASET="qotd"
```

The OAuth refresh token must include Gmail read, send, and modify access so the adjustment job can find requests, reply to them, and remove the unread label after handling.

## Email Management Jobs

The GitHub Actions workflow `.github/workflows/qotd-score-adjustments.yml` runs management email processing at `13:55 UTC` on weekdays, five minutes before the QOTD scoring workflow. It processes correct-answer requests first, then score-adjustment requests. It shares a concurrency group with the scoring workflow so state writes do not overlap.

## Correct Answer Emails

When Cody manually sends a QOTD from `***SECRET***`, send a correct-answer email before scoring:

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

## Email Score Adjustments

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

## Local Score Adjustments

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

## Manual Scoring Reruns

Rerun scoring for a specific game date with:

```bash
python -m qotd score-responses --game-date 2026-07-08
```

Use `--dry-run` to fetch replies and render the organizer update body without sending the organizer email.
