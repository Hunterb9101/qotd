# For Developers

This guide covers local installation, developer configuration, question-generation tools, and tests.

## Requirements

QOTD requires Python 3.13 or newer.

## Local Installation

Create a virtual environment and install the dependencies:

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

## Configuration

Production-facing commands use Gmail and BigQuery. Provide their configuration through environment variables or the corresponding CLI options:

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

Scoring uses OpenAI to interpret freeform replies that are not a plain `A`, `B`, `C`, or `D`. Set `OPENAI_INTERPRETER_MODEL` to override the default model. Pass `--disable-ai-answer-interpreter` when you need deterministic-only local scoring.

See the [Organizer guide](for-organizers.md) for production account, OAuth, and GitHub Actions setup.

## Generate Sample Questions

Generate question candidates for a topic without sending email or reading or writing production state:

```bash
python -m qotd generate-samples --topic "cheese history" --count 3
```

The command requires `OPENAI_API_KEY` and uses `OPENAI_GENERATOR_MODEL` when set. The generator can research each candidate with web search.

Samples draw from the defined trivia categories without repeating one until the set is exhausted. Pass `--category` to use one category for the entire batch. The command prints structured JSON containing each question, four options, the correct option, and source metadata.

## Tests

Run the offline test suite with:

```bash
python -m pytest tests/
```

Live Answer-interpreter evaluations are in `tests/usecases/test_score_submissions.py`. They use the `intg` pytest marker and run only when explicitly selected:

```bash
OPENAI_API_KEY="..." pytest -m intg
```

Set `OPENAI_INTERPRETER_MODEL` to select the live evaluation model. Explicit integration runs fail with a configuration error when `OPENAI_API_KEY` is missing.

Canonical BigQuery changes must also pass the isolated-storage integration test before deployment. Create an empty non-production dataset whose name ends in `_test`, then configure it separately from production:

```bash
export QOTD_BIGQUERY_TEST_PROJECT="your-test-project"
export QOTD_BIGQUERY_TEST_DATASET="qotd_test"
export GOOGLE_OAUTH_CLIENT_ID="..."
export GOOGLE_OAUTH_CLIENT_SECRET="..."
export GOOGLE_OAUTH_REFRESH_TOKEN="..."
python -m pytest -m intg tests/external/storage/test_bigquery_integration.py
```

The test applies the canonical schema only to that test dataset, writes a uniquely named Player, Game, Submission, and Score Event, and verifies the resulting Scoreboard. It never sends email and refuses any dataset not ending in `_test`.

Before any BigQuery write-path change, run the no-write SQL validation against an existing dataset with the canonical schema:

```bash
export QOTD_BIGQUERY_DRY_RUN_PROJECT="your-project"
export QOTD_BIGQUERY_DRY_RUN_DATASET="qotd"
python -m pytest -m intg tests/external/storage/test_bigquery.py \
  -k dry_run_validates_scoring_transaction_sql
```

This submits the exact generated Submission and Game-scoring transactions as BigQuery dry runs. It validates GoogleSQL syntax and table references but does not execute DML, modify data, or access Gmail.

GitHub Actions runs this same dry-run validation automatically for every push to `main` in `qotd-bigquery-validate.yml`.

## Related Documentation

- [Technical notes](technical-notes.md)
- [Tone guidelines](qotd_tone_guidelines.md)
- [Game lifecycle](game-lifecycle.md)
- [Architecture decision: automatic sending](adr/adr-001-auto-send.md)
- [Initial product requirements](prd/prd-initial.md)
