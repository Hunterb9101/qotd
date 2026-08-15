"""Time source used by deterministic QOTD workflows."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol


class Clock(Protocol):
    """Provide the current timezone-aware instant."""

    def now(self) -> datetime: ...


class SystemClock:
    """Read the current UTC time from the system clock."""

    def now(self) -> datetime:
        return datetime.now(UTC)
