#!/usr/bin/env python3
"""One-time canonical QOTD BigQuery setup."""

from __future__ import annotations

import argparse
import os

from qotd.external.storage.bigquery import build_bigquery_state_store
from qotd.provision import provision_canonical_state


def main() -> None:
    """Apply the reviewed canonical schema to one existing dataset."""

    parser = argparse.ArgumentParser(description="One-time canonical QOTD database setup")
    parser.add_argument("--project", default=os.environ.get("GOOGLE_CLOUD_PROJECT", ""))
    parser.add_argument("--dataset", default=os.environ.get("BIGQUERY_DATASET", "qotd"))
    parser.add_argument("--reset-legacy-state", action="store_true")
    args = parser.parse_args()
    required = ("GOOGLE_OAUTH_CLIENT_ID", "GOOGLE_OAUTH_CLIENT_SECRET", "GOOGLE_OAUTH_REFRESH_TOKEN")
    missing = [name for name in required if not os.environ.get(name)]
    if not args.project or missing:
        parser.error("--project and Google OAuth environment variables are required")
    state = build_bigquery_state_store(
        project_id=args.project, dataset=args.dataset,
        oauth_client_id=os.environ["GOOGLE_OAUTH_CLIENT_ID"],
        oauth_client_secret=os.environ["GOOGLE_OAUTH_CLIENT_SECRET"],
        oauth_refresh_token=os.environ["GOOGLE_OAUTH_REFRESH_TOKEN"],
    )
    provision_canonical_state(
        client=state.client, project_id=args.project, dataset=args.dataset,
        reset_legacy_state=args.reset_legacy_state,
    )


if __name__ == "__main__":
    main()
