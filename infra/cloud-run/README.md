# Cloud Run Jobs deployment

This directory defines the planned replacement for the scheduled GitHub
Actions workflows. It creates two immutable-image Cloud Run Jobs and two paused
Cloud Scheduler triggers. A Job is a stable deployed
definition; each scheduled invocation creates an **execution**, not a new
deployment.

The configuration uses the QOTD terms in [Definitions](../../docs/DEFINITIONS.md):
the morning Job processes **Organizer Instructions**, then scores the prior
**Game** and send its organizer update; the noon job publishes a **Question**
for the current **Day**.

## Declared schedule

All schedules use `America/Denver`, which is QOTD's [Day](../../docs/DEFINITIONS.md#day)
timezone. Cloud Scheduler adjusts for daylight saving time.

| Scheduler trigger | Cloud Run Job / QOTD command | Weekday local time |
| --- | --- | --- |
| `qotd-morning` | `qotd-morning` / `process-set-answers`, then `process-score-events`, then `score-responses --skip-if-missing-question` | 7:55 AM |
| `qotd-publish` | `qotd-publish` / `publish-question` | noon |

The morning commands run serially in one Job. Answer Instructions are processed
before manual Score Event Instructions, which both finish before scoring begins.
Both Jobs receive `OPENAI_API_KEY`: the morning Job uses it to interpret
freeform Player Submissions during scoring, and the publication Job uses it to
generate the Question.

`deploy.sh` creates or updates every Scheduler job and then pauses it. This
makes the first deployment safe: no scheduled execution can race the current
GitHub Actions schedule, and makes subsequent reviewed deployments rerunnable.

Cloud Run's `parallelism=1` prevents parallel Tasks within one Job. Combining
the morning work into one Job preserves the existing required ordering without
depending on a cross-Job scheduler mutex.

## Required secrets

Before deploying, create these Secret Manager secrets in
`question-of-the-day-501919` and add a real, enabled version containing the
corresponding current GitHub `prod` environment value. Cloud Run validates
secret versions during Job creation, so placeholder or empty values cannot be
used for an initial deployment. Do not place values in this repository, an
image, Cloud Build substitutions, or command-line arguments.

| Secret Manager secret | Environment variable |
| --- | --- |
| `google-oauth-client-id` | `GOOGLE_OAUTH_CLIENT_ID` |
| `google-oauth-client-secret` | `GOOGLE_OAUTH_CLIENT_SECRET` |
| `google-oauth-refresh-token` | `GOOGLE_OAUTH_REFRESH_TOKEN` |
| `qotd-sender` | `QOTD_SENDER` |
| `qotd-google-group-email` | `QOTD_GOOGLE_GROUP_EMAIL` |
| `openai-api-key` | `OPENAI_API_KEY` |

The non-secret environment is in [job-environment.yaml](job-environment.yaml).

## IAM prerequisites

The provisioned runtime identity is `qotd-runner@question-of-the-day-501919.iam.gserviceaccount.com`.
Create a separate Scheduler caller rather than using a default Compute Engine
identity.

```sh
PROJECT_ID=question-of-the-day-501919
RUNTIME_SERVICE_ACCOUNT=qotd-runner@${PROJECT_ID}.iam.gserviceaccount.com
SCHEDULER_SERVICE_ACCOUNT=qotd-scheduler@${PROJECT_ID}.iam.gserviceaccount.com

gcloud iam service-accounts create qotd-scheduler --project="$PROJECT_ID"
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:${RUNTIME_SERVICE_ACCOUNT}" --role=roles/secretmanager.secretAccessor
gcloud run jobs add-iam-policy-binding qotd-morning \
  --project="$PROJECT_ID" --region=us-central1 \
  --member="serviceAccount:${SCHEDULER_SERVICE_ACCOUNT}" --role=roles/run.invoker
```

The final binding is representative: grant `roles/run.invoker` to the Scheduler
identity on each of the two Jobs after deployment. The current application
creates its BigQuery client with the configured Google OAuth user credentials,
not the Cloud Run runtime identity, so it does not require BigQuery IAM roles on
`qotd-runner`. Revisit this if the application later adopts service-account
BigQuery authentication.

## Build and deploy (paused)

From a clean commit, build and push an immutable image tag. Substitute a tag
derived from the reviewed commit SHA; never deploy `latest`.

```sh
gcloud builds submit --project=question-of-the-day-501919 \
  --tag=us-central1-docker.pkg.dev/question-of-the-day-501919/qotd/qotd:COMMIT_SHA
IMAGE_TAG=COMMIT_SHA bash infra/cloud-run/deploy.sh
```

Grant the Scheduler identity invoker access on all Jobs, then inspect the
paused triggers and execute each Job manually once. Confirm the expected
BigQuery and Gmail effects before changing schedules.

```sh
gcloud scheduler jobs list --project=question-of-the-day-501919 --location=us-central1
gcloud run jobs execute qotd-morning --project=question-of-the-day-501919 --region=us-central1 --wait
```

Do not manually execute `qotd-publish-question` against production merely to
smoke-test the container: that can publish a real Question. Validate it with a
reviewed non-production configuration or during the deliberate cutover window.

## Cutover and rollback

1. Keep both Scheduler jobs paused. Build, deploy, verify IAM bindings, and
   inspect the rendered Job configuration.
2. Choose a cutover before the 7:55 AM `America/Denver` window. Disable the
   three scheduled GitHub Actions workflows first, while retaining manual
   dispatch for recovery.
3. Resume `qotd-morning`, then `qotd-publish`. Confirm their `state=ENABLED`
   and check the first executions in Cloud Run logs.
4. If any production problem occurs, immediately pause all Scheduler triggers.
   The QOTD **Game**, **Score Event**, and **Outbound Message** state is
   idempotent, but do not run both schedulers simultaneously during recovery.
5. Re-enable only the corresponding GitHub Actions scheduled workflow or run a
   single reviewed manual recovery command after checking the canonical state.
   Retain the Cloud Run Jobs and logs for diagnosis; do not delete the Jobs as
   part of rollback.

Configure a Cloud Monitoring alert for failed Cloud Run Job executions and a
second alert for no successful scoring or publication execution on a weekday.
