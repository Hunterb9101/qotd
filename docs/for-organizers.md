# For Organizers

This guide covers production setup and the human workflows used to operate QOTD. Operators interact with QOTD through email and GitHub Actions; no local installation or Python commands are required.

## Production Schedule

GitHub Actions runs the weekday game on the following schedule in
`America/Denver` time:

- 7 AM: Player Submission cutoff
- 8 AM: scoring update sent to the Organizer
- noon: Question sent to Players

The management-email workflow runs at `13:55 UTC` (7:55 AM during daylight
time and 6:55 AM during standard time). It processes Answer instructions first
and Manual Score Event instructions second. Both workflows share a concurrency
group so their state writes do not overlap.

## Email and Players

QOTD uses a Gmail account to send questions, collect replies, and receive organizer controls. Automated questions go to a private, invitation-only Google Group rather than directly to a blind-copy recipient list.

Configure the Group so that:

- only the organizer can post;
- replies go to the original author;
- conversations and membership are private; and
- the standard subscription footer is enabled.

Google Group membership is the only Player list. QOTD correlates replies with
the applicable Question. The current Series Scoreboard includes every Player
with a Submission or Score Event in that Series, including zero and negative
Scores; non-respondent reporting uses that Scoreboard.

Use the same Google account to configure Google Cloud Platform.

## OpenAI Account

Create an OpenAI API key for topic discovery, question generation, and freeform-answer interpretation.

## Google Cloud Platform

Enable the Gmail and BigQuery APIs. QOTD needs these OAuth scopes:

- `.../auth/bigquery` for database access
- `.../auth/gmail.modify` to label manually sent QOTD emails
- `.../auth/gmail.readonly` to collect Player Submissions for scoring
- `.../auth/gmail.send` to send QOTD email

A service account works only when you control the Google Workspace domain, so other installations should use OAuth access.

QOTD stores Game state in a BigQuery dataset. Google Cloud requires a billing account for DML SQL commands, although this project's small workload should remain within the free tier.

Before enabling canonical workflows, pause the scheduled workflows and provision an existing, reviewed target dataset locally:

```sh
python scripts/seed_db.py --project question-of-the-day-501919 --dataset qotd --reset-legacy-state
```

This operator-only command verifies the configured project and dataset before executing SQL. The reset option drops only the five named legacy QOTD tables, then applies the versioned canonical schema; it never drops the dataset.

Before re-enabling workflows, create the active Series by publishing or setting
an Answer for its first Game, then verify the canonical tables and the empty
Series Scoreboard in BigQuery.

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

## Manual Questions and Answers

QOTD respects a question sent manually from the configured organizer address. Send the question to the private Google Group with this exact subject:

```text
QOTD - MM-DD-YY
```

For example, the subject for July 8, 2026 is:

```text
QOTD - 07-08-26
```

The subject is case-sensitive and must not contain any extra text. Use the email body for the Question and its four options that Players should receive.

Before the manual Question is scored, send a plain-text Organizer Instruction from an approved Organizer address to the QOTD admin mailbox. The email has no required subject; `QOTD Answer - 07-08-26` is a useful convention. Its body must follow this format:

```text
Action: set-answer
Day: 2026-07-08
Correct option: C
Source URL: https://example.com/source-for-answer
```

The management job finds unread emails containing `Action: set-answer` and validates the Organizer sender, Game Day, Answer option, source URL, and idempotency identity. If a manual Game has no Answer, scoring skips that Day and emails the expected template to the Organizer.

The scheduled `Process QOTD Score Events` workflow processes the email before scoring. To process it immediately, open that workflow in the repository's **Actions** tab and choose **Run workflow**.

## Manual Score Event Email

To create a manual Score Event, send a plain-text Organizer Instruction from an approved Organizer address to the QOTD Gmail account configured in `QOTD_SENDER`. If the Organizer address and QOTD account are the same, send the email to that account itself.

The subject is not enforced. A useful subject is:

```text
QOTD Score Event - 2026-07-08
```

For example, this request adds one point to `person@example.com` for the July 8 question:

```text
Action: record-score-event
Player: person@example.com
Day: 2026-07-08
Points: 1
Reason: unclear answer accepted
```

`Points` is the change to the Player's Score, not the desired total. Use a positive integer such as `1` to add points or a negative integer such as `-1` to remove them. `Reason` can be a short plain-language explanation.

Use `Day` when the Score Event is tied to a particular Game. For a Series-wide Score Event, use `Month` instead:

```text
Action: record-score-event
Player: person@example.com
Month: 2026-07
Points: -1
Reason: duplicate correction
```

Do not include both `Day` and `Month`. A `Gmail message ID` is optional and normally should be omitted.

After sending the request:

1. Leave the email unread.
2. Wait for the scheduled **Process QOTD Score Events** workflow, or open it in the repository's **Actions** tab and choose **Run workflow** to process the request immediately.
3. Check the response email with the subject `QOTD Manual Score Event result`. It confirms the updated Score and Scoreboard or explains why the request was rejected.

After processing a request, QOTD marks it as read so it will not be handled again.

## Manual Scoring Reruns

To rerun scoring for a specific Day:

1. Open the repository's **Actions** tab.
2. Select **Score QOTD Responses**.
3. Choose **Run workflow**.
4. Enter the question date in `YYYY-MM-DD` format in the `game_date` field.
5. Run the workflow.

Leaving `game_date` blank scores the previous game day.
