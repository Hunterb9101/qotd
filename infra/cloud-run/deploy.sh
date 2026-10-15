#!/usr/bin/env bash
# Declare the QOTD Cloud Run Jobs and their initially-paused Cloud Scheduler
# triggers. Run only after reviewing infra/cloud-run/README.md.
set -euo pipefail

PROJECT_ID="${PROJECT_ID:-question-of-the-day-501919}"
REGION="${REGION:-us-central1}"
REPOSITORY="${REPOSITORY:-qotd}"
IMAGE_TAG="${IMAGE_TAG:?Set IMAGE_TAG to an immutable image tag or digest.}"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPOSITORY}/qotd:${IMAGE_TAG}"
RUNTIME_SERVICE_ACCOUNT="${RUNTIME_SERVICE_ACCOUNT:-qotd-runner@${PROJECT_ID}.iam.gserviceaccount.com}"
SCHEDULER_SERVICE_ACCOUNT="${SCHEDULER_SERVICE_ACCOUNT:-qotd-scheduler@${PROJECT_ID}.iam.gserviceaccount.com}"
ENV_FILE="infra/cloud-run/job-environment.yaml"
# ``preserve`` is appropriate for normal redeploys: changing the Job image
# must not silently stop an enabled production schedule. New triggers remain
# paused so that an initial deployment still requires an explicit cutover.
SCHEDULER_MODE="${SCHEDULER_MODE:-preserve}"
# Runtime image deployments do not need permission to alter Scheduler. Leave
# trigger management to explicit infrastructure/cutover deployments.
MANAGE_SCHEDULERS="${MANAGE_SCHEDULERS:-true}"

case "$SCHEDULER_MODE" in
  preserve|paused) ;;
  *)
    echo "SCHEDULER_MODE must be 'preserve' or 'paused'; got: $SCHEDULER_MODE" >&2
    exit 2
    ;;
esac

case "$MANAGE_SCHEDULERS" in
  true|false) ;;
  *)
    echo "MANAGE_SCHEDULERS must be 'true' or 'false'; got: $MANAGE_SCHEDULERS" >&2
    exit 2
    ;;
esac

# Every listed secret must have a real, enabled Secret Manager version before
# deploying. Cloud Run validates each binding when the Job is created, so empty
# placeholder secrets cannot be used. Binding `latest` is intentional only
# while migration is in progress; pin a numbered version after the initial
# cutover if secret rotation needs staged rollout.
COMMON_SECRETS="GOOGLE_OAUTH_CLIENT_ID=google-oauth-client-id:latest,GOOGLE_OAUTH_CLIENT_SECRET=google-oauth-client-secret:latest,GOOGLE_OAUTH_REFRESH_TOKEN=google-oauth-refresh-token:latest,QOTD_SENDER=qotd-sender:latest"
OPENAI_SECRET="OPENAI_API_KEY=openai-api-key:latest"
PUBLISH_SECRET="QOTD_GOOGLE_GROUP_EMAIL=qotd-google-group-email:latest"

job_uri() {
  printf 'https://run.googleapis.com/v2/projects/%s/locations/%s/jobs/%s:run' "$PROJECT_ID" "$REGION" "$1"
}

deploy_python_job() {
  local job_name="$1"
  local command="$2"
  local secret_bindings="$3"

  gcloud run jobs deploy "$job_name" \
    --project="$PROJECT_ID" \
    --region="$REGION" \
    --image="$IMAGE" \
    --service-account="$RUNTIME_SERVICE_ACCOUNT" \
    --env-vars-file="$ENV_FILE" \
    --set-secrets="$secret_bindings" \
    --command=python \
    --args="-m,qotd,${command}" \
    --task-timeout=20m \
    --max-retries=1 \
    --parallelism=1 \
    --tasks=1
}

# The morning Job preserves the existing workflow ordering in one execution:
# Organizer Instructions, then response scoring. This avoids relying on a
# scheduler-level mutex between independently deployed Jobs.
gcloud run jobs deploy qotd-morning \
  --project="$PROJECT_ID" \
  --region="$REGION" \
  --image="$IMAGE" \
  --service-account="$RUNTIME_SERVICE_ACCOUNT" \
  --env-vars-file="$ENV_FILE" \
  --set-secrets="$COMMON_SECRETS,$OPENAI_SECRET" \
  --command=/bin/sh \
  --args='-c,python -m qotd process-set-answers && python -m qotd process-score-events && python -m qotd score-responses --skip-if-missing-question' \
  --task-timeout=20m \
  --max-retries=1 \
  --parallelism=1 \
  --tasks=1
deploy_python_job qotd-publish 'publish-question' "$COMMON_SECRETS,$OPENAI_SECRET,$PUBLISH_SECRET"

# Cloud Scheduler's timezone support keeps these at the product's required
# America/Denver local times through daylight-saving transitions. Every trigger
# is paused after its initial creation. Normal image redeploys preserve an
# existing trigger's enabled/paused state; set SCHEDULER_MODE=paused when a
# maintenance deploy must explicitly pause all triggers.
upsert_paused_scheduler() {
  local scheduler_name="$1"
  local schedule="$2"
  local job_name="$3"

  if gcloud scheduler jobs describe "$scheduler_name" --project="$PROJECT_ID" --location="$REGION" >/dev/null 2>&1; then
    gcloud scheduler jobs update http "$scheduler_name" \
      --project="$PROJECT_ID" \
      --location="$REGION" \
      --schedule="$schedule" \
      --time-zone='America/Denver' \
      --http-method=POST \
      --uri="$(job_uri "$job_name")" \
      --oauth-service-account-email="$SCHEDULER_SERVICE_ACCOUNT" \
      --oauth-token-scope='https://www.googleapis.com/auth/cloud-platform' \
      --attempt-deadline=30m \
      --max-retry-attempts=1 \
      --max-backoff=15m
  else
    gcloud scheduler jobs create http "$scheduler_name" \
      --project="$PROJECT_ID" \
      --location="$REGION" \
      --schedule="$schedule" \
      --time-zone='America/Denver' \
      --http-method=POST \
      --uri="$(job_uri "$job_name")" \
      --oauth-service-account-email="$SCHEDULER_SERVICE_ACCOUNT" \
      --oauth-token-scope='https://www.googleapis.com/auth/cloud-platform' \
      --attempt-deadline=30m \
      --max-retry-attempts=1 \
      --max-backoff=15m
    # A new trigger is deliberately paused, independent of deploy mode.
    gcloud scheduler jobs pause "$scheduler_name" --project="$PROJECT_ID" --location="$REGION"
    return
  fi

  if [[ "$SCHEDULER_MODE" == "paused" ]]; then
    gcloud scheduler jobs pause "$scheduler_name" --project="$PROJECT_ID" --location="$REGION"
  fi
}

if [[ "$MANAGE_SCHEDULERS" == "true" ]]; then
  upsert_paused_scheduler qotd-morning '55 7 * * 1-5' qotd-morning
  upsert_paused_scheduler qotd-publish '0 12 * * 1-5' qotd-publish
fi
