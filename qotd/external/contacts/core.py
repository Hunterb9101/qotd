"""Implementation-agnostic contacts client contract."""

from __future__ import annotations

from abc import ABC, abstractmethod


class ContactsClient(ABC):
    """Client interface for participant contact lookup."""

    @abstractmethod
    def fetch_group_email_addresses(self, group_name: str) -> list[str]:
        """Fetch email addresses for one contact group."""
