"""Email normalization helpers for QOTD Players."""

from __future__ import annotations

from collections.abc import Iterable


def normalize_email_addresses(email_addresses: Iterable[str]) -> list[str]:
    """Normalize, dedupe, and sort email addresses."""

    normalized = {
        email_address.strip().lower()
        for email_address in email_addresses
        if email_address.strip()
    }
    return sorted(normalized)
