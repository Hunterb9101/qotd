# For Operators

This guide covers production setup and the human workflows used to operate QOTD. Operators interact with QOTD through email and GitHub Actions; no local installation or Python commands are required.

## Production Schedule

GitHub Actions runs the weekday game on the following schedule:

- 6 AM PDT: participant scoring cutoff
- 7 AM PDT: scoring summary sent to the organizer
- 2 PM PDT: trivia question sent to participants

The management-email workflow runs at `13:55 UTC`, five minutes before the scoring workflow. It processes correct-answer requests first and score-adjustment requests second. Both workflows share a concurrency group so their state writes do not overlap.

## Email and Participants

QOTD uses a Gmail account to send questions, collect replies, and receive organizer controls. Automated questions go to a private, invitation-only Google Group rather than directly to a blind-copy recipient list.

Configure the Group so that:

- only the organizer can post;
- replies go to the original author;
- conversations and membership are private; and
- the standard subscription footer is enabled.

Google Group membership is the only participant list. QOTD correlates replies with the applicable question and includes only participants with positive points in current-month standings and non-respondent reporting.

Use the same Google account to configure Google Cloud Platform.

## OpenAI Account

Create an OpenAI API key for topic discovery, question generation, and freeform-answer interpretation.

## Google Cloud Platform

Enable the Gmail and BigQuery APIs. QOTD needs these OAuth scopes:

- `.../auth/bigquery` for database access
- `.../auth/gmail.modify` to label manually sent QOTD emails
- `.../auth/gmail.readonly` to score participant responses
- `.../auth/gmail.send` to send QOTD email

A service account works only when you control the Google Workspace domain, so other installations should use OAuth access.

QOTD stores previously asked questions, participant scores, and other game state in a BigQuery dataset. Google Cloud requires a billing account for DML SQL commands, although this project's small workload should remain within the free tier.

## GitHub Actions

Create a GitHub Actions environment named `production` and add these environment secrets:

- `QOTD_SENDER`
- `QOTD_GOOGLE_GROUP_EMAIL`
- `GOOGLE_OAUTH_CLIENT_ID`
- `GOOGLE_OAUTH_CLIENT_SECRET`
- `GOOGLE_OAUTH_REFRESH_TOKEN`
- `OPENAI_API_KEY`

`QOTD_GOOGLE_GROUP_EMAIL` is the private Group's `@googlegroups.com` address. Generate the three Google OAuth values with `scripts/generate_oauth_refresh_token.py`, signing in with the organizer email stored in `QOTD_SENDER`.

Set `GOOGLE_CLOUD_PROJECT` to the Google Cloud project used by QOTD.

The production workflows live in `.github/workflows`:

- `qotd-send.yml` sends questions.
- `qotd-score.yml` scores replies and reports results.
- `qotd-score-adjustments.yml` processes management email.

## Manual Questions and Correct Answers

QOTD respects a question sent manually from the configured organizer address. Send the question to the private Google Group with this exact subject:

```text
QOTD - MM-DD-YY
```

For example, the subject for July 8, 2026 is:

```text
QOTD - 07-08-26
```

The subject is case-sensitive and must not contain any extra text. Use the email body for the question and answer choices that participants should receive.

Before the manual question is scored, send a plain-text correct-answer email from an approved organizer address to the QOTD admin mailbox. The answer email has no required subject; `QOTD Correct Answer - 07-08-26` is a useful convention. Its body must follow this format:

```text
Action: set-correct-answer
Game date: 2026-07-08
Correct option: C
Source URL: https://example.com/source-for-answer
```

The management job finds unread emails containing `Action: set-correct-answer` and validates the organizer sender, stored question date, option, source URL, and idempotency key. If a manual question has no correct answer, scoring skips that game date and emails the expected template to the organizer.

The scheduled `Process QOTD Score Adjustments` workflow processes the email before scoring. To process it immediately, open that workflow in the repository's **Actions** tab and choose **Run workflow**.

## Score Adjustments by Email

To correct a score, send a new plain-text email from an approved organizer address to the QOTD Gmail account configured in `QOTD_SENDER`. If the organizer address and QOTD account are the same, send the email to that account itself.

The subject is not enforced. A useful subject is:

```text
QOTD Score Adjustment - 2026-07-08
```

For example, this request adds one point to `person@example.com` for the July 8 question:

```text
Action: adjust-score
Participant: person@example.com
Game date: 2026-07-08
Points: 1
Reason: unclear answer accepted
```

`Points` is the change to the participant's score, not the desired total. Use a positive integer such as `1` to add points or a negative integer such as `-1` to remove them. `Reason` can be a short plain-language explanation.

Use `Game date` when the correction is tied to a particular question. For a correction that applies to the month generally, use `Month` instead:

```text
Action: adjust-score
Participant: person@example.com
Month: 2026-07
Points: -1
Reason: duplicate correction
```

Do not include both `Game date` and `Month`. A `Gmail message ID` is optional and normally should be omitted.

After sending the request:

1. Leave the email unread.
2. Wait for the scheduled **Process QOTD Score Adjustments** workflow, or open it in the repository's **Actions** tab and choose **Run workflow** to process the request immediately.
3. Check the response email with the subject `QOTD score adjustment result`. It confirms the updated score and standings or explains why the request was rejected.

After processing a request, QOTD marks it as read so it will not be handled again.

## Manual Scoring Reruns

To rerun scoring for a specific game date:

1. Open the repository's **Actions** tab.
2. Select **Score QOTD Responses**.
3. Choose **Run workflow**.
4. Enter the question date in `YYYY-MM-DD` format in the `game_date` field.
5. Run the workflow.

Leaving `game_date` blank scores the previous game day.
