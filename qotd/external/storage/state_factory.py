"""State store construction helpers."""

from __future__ import annotations

from qotd.external.storage.bigquery_storage import BigQueryStateStore


def build_bigquery_state_store(
    *,
    project_id: str,
    dataset: str,
    oauth_client_id: str,
    oauth_client_secret: str,
    oauth_refresh_token: str,
) -> BigQueryStateStore:
    """Build the production BigQuery state store."""

    if not project_id:
        raise ValueError("Google Cloud project is required")
    if not dataset:
        raise ValueError("BigQuery dataset is required")
    return BigQueryStateStore.from_oauth(
        project_id=project_id,
        dataset=dataset,
        oauth_client_id=oauth_client_id,
        oauth_client_secret=oauth_client_secret,
        oauth_refresh_token=oauth_refresh_token,
    )
