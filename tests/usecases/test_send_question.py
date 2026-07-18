from __future__ import annotations

from datetime import date

import pytest

from qotd.usecases.send_question import SendQuestionConfig, send_question
from tests.support import InMemoryStateStore


def test_production_send_requires_google_group_address() -> None:
    """Fail closed instead of reverting to multi-recipient Bcc delivery."""

    with pytest.raises(RuntimeError, match="Google Group email"):
        send_question(
            SendQuestionConfig(
                game_date=date(2026, 7, 9),
                sender="sender@example.com",
                state_store=InMemoryStateStore(),
                gmail_user="sender@example.com",
                oauth_client_id="",
                oauth_client_secret="",
                oauth_refresh_token="",
            ),
            fetch_messages=lambda _query: [],
        )
