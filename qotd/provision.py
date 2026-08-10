"""Operator-only provisioning for the canonical QOTD BigQuery state."""

from __future__ import annotations

import importlib
import re
from pathlib import Path
from typing import Any


SQL_DIRECTORY = Path(__file__).parent.parent / "sql"
CANONICAL_SCHEMA = SQL_DIRECTORY / "001_canonical_state.sql"
LEGACY_RESET = SQL_DIRECTORY / "002_reset_legacy_state.sql"
_PROJECT_ID = re.compile(r"[a-z][a-z0-9-]{4,61}[a-z0-9]")
_DATASET_ID = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,1023}")


def validate_target(*, project_id: str, dataset: str) -> None:
    """Reject malformed project and dataset identifiers before any API call."""

    if not _PROJECT_ID.fullmatch(project_id):
        raise ValueError("Invalid Google Cloud project id")
    if not _DATASET_ID.fullmatch(dataset):
        raise ValueError("Invalid BigQuery dataset id")


def provision_canonical_state(
    *, client: Any, project_id: str, dataset: str, reset_legacy_state: bool = False
) -> None:
    """Validate an existing target dataset and apply canonical QOTD DDL."""

    validate_target(project_id=project_id, dataset=dataset)
    bigquery = importlib.import_module("google.cloud.bigquery")
    target = f"{project_id}.{dataset}"
    dataset_ref = client.get_dataset(target)
    if dataset_ref.project != project_id or dataset_ref.dataset_id != dataset:
        raise ValueError("BigQuery returned a dataset other than the requested target")

    job_config = bigquery.QueryJobConfig(default_dataset=dataset_ref.reference)
    scripts = [LEGACY_RESET, CANONICAL_SCHEMA] if reset_legacy_state else [CANONICAL_SCHEMA]
    for script in scripts:
        client.query(script.read_text(), job_config=job_config).result()
