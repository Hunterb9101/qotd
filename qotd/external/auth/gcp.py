"""Google Cloud and Google API OAuth credential helpers."""

from __future__ import annotations

import importlib
from collections.abc import Sequence
from typing import Any


GOOGLE_TOKEN_URI = "https://oauth2.googleapis.com/token"
GOOGLE_OAUTH_SCOPES = (
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/bigquery",
)


def build_oauth_credentials(
    *,
    client_id: str,
    client_secret: str,
    refresh_token: str,
    scopes: Sequence[str] = GOOGLE_OAUTH_SCOPES,
) -> Any:
    """Build OAuth credentials for a consumer Google account."""

    if not client_id:
        raise ValueError("Google OAuth client ID is required")
    if not client_secret:
        raise ValueError("Google OAuth client secret is required")
    if not refresh_token:
        raise ValueError("Google OAuth refresh token is required")

    credentials_module = importlib.import_module("google.oauth2.credentials")
    return credentials_module.Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri=GOOGLE_TOKEN_URI,
        client_id=client_id,
        client_secret=client_secret,
        scopes=list(scopes),
    )
