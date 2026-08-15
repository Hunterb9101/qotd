"""Controllable time source for acceptance scenarios."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class FixedClock:
    """Return one explicit instant for a deterministic workflow step."""

    current: datetime

    def now(self) -> datetime:
        return self.current
