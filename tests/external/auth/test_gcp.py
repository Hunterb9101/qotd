"""Tests for Google OAuth credential configuration."""

from qotd.external.auth.gcp import GOOGLE_OAUTH_SCOPES as RUNTIME_GOOGLE_OAUTH_SCOPES
from scripts.generate_oauth_refresh_token import GOOGLE_OAUTH_SCOPES as TOKEN_GOOGLE_OAUTH_SCOPES


def test_token_helper_requests_all_runtime_google_oauth_scopes() -> None:
    """Ensure generated refresh tokens cover every production Google operation."""

    assert TOKEN_GOOGLE_OAUTH_SCOPES == RUNTIME_GOOGLE_OAUTH_SCOPES
