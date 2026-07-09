"""Gmail API helpers for reading QOTD messages."""

from __future__ import annotations

import importlib
from typing import Any

from qotd.auth import build_oauth_credentials


GMAIL_READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"


def build_gmail_service(
    *,
    oauth_client_id: str,
    oauth_client_secret: str,
    oauth_refresh_token: str,
    scopes: list[str] | None = None,
) -> Any:
    """Build a Gmail API service."""

    discovery = importlib.import_module("googleapiclient.discovery")
    credentials = build_oauth_credentials(
        client_id=oauth_client_id,
        client_secret=oauth_client_secret,
        refresh_token=oauth_refresh_token,
        scopes=scopes or [GMAIL_READONLY_SCOPE],
    )
    return discovery.build("gmail", "v1", credentials=credentials, cache_discovery=False)


def list_message_ids(service: Any, *, user_id: str, query: str, max_results: int = 100) -> list[str]:
    """List Gmail message ids matching a search query."""

    message_ids: list[str] = []
    request = service.users().messages().list(userId=user_id, q=query, maxResults=max_results)
    while request is not None:
        response = request.execute()
        for message in response.get("messages", []):
            message_id = message.get("id")
            if isinstance(message_id, str):
                message_ids.append(message_id)
        request = service.users().messages().list_next(request, response)
    return message_ids


def get_message(service: Any, *, user_id: str, message_id: str) -> dict[str, Any]:
    """Fetch one Gmail message in full format."""

    response = (
        service.users()
        .messages()
        .get(userId=user_id, id=message_id, format="full")
        .execute()
    )
    if not isinstance(response, dict):
        raise RuntimeError(f"Gmail message response was not an object: {message_id}")
    return response


def search_messages(
    *,
    user_id: str,
    oauth_client_id: str,
    oauth_client_secret: str,
    oauth_refresh_token: str,
    query: str,
    max_results: int = 100,
) -> list[dict[str, Any]]:
    """Search Gmail and return full message resources."""

    service = build_gmail_service(
        oauth_client_id=oauth_client_id,
        oauth_client_secret=oauth_client_secret,
        oauth_refresh_token=oauth_refresh_token,
    )
    return [
        get_message(service, user_id=user_id, message_id=message_id)
        for message_id in list_message_ids(
            service,
            user_id=user_id,
            query=query,
            max_results=max_results,
        )
    ]
