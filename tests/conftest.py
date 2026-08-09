"""Shared canonical-state fixtures for QOTD business-flow tests."""

from datetime import UTC, datetime

import pytest

from tests.support import FixedClock, InMemoryCanonicalState, InMemoryMailbox


@pytest.fixture
def fixed_clock() -> FixedClock:
    return FixedClock(datetime(2026, 8, 10, 12, tzinfo=UTC))


@pytest.fixture
def canonical_state(fixed_clock: FixedClock) -> InMemoryCanonicalState:
    return InMemoryCanonicalState(clock=fixed_clock)


@pytest.fixture
def mailbox() -> InMemoryMailbox:
    return InMemoryMailbox()
