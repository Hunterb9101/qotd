"""Google People API contacts adapter."""

from __future__ import annotations

import importlib
from collections.abc import Iterable, Sequence
from typing import Any

from qotd.domain.contacts import normalize_email_addresses
from qotd.external.auth.gcp import build_oauth_credentials
from qotd.external.contacts.core import ContactsClient


CONTACTS_READONLY_SCOPE = "https://www.googleapis.com/auth/contacts.readonly"
MAX_BATCH_GET_PEOPLE = 200


def chunked(values: Sequence[str], size: int) -> Iterable[Sequence[str]]:
    """Yield fixed-size chunks from a sequence."""

    for index in range(0, len(values), size):
        yield values[index : index + size]


def find_contact_group(contact_groups: Sequence[dict[str, Any]], group_name: str) -> dict[str, Any]:
    """Find one Google contact group by exact display name."""

    matches = [group for group in contact_groups if group.get("name") == group_name]
    if not matches:
        raise RuntimeError(f"Contact group not found: {group_name}")
    if len(matches) > 1:
        raise RuntimeError(f"Multiple contact groups found with name: {group_name}")
    return matches[0]


def extract_email_addresses(people_responses: Sequence[dict[str, Any]]) -> list[str]:
    """Extract normalized email addresses from People API batch responses."""

    email_addresses: list[str] = []
    for response in people_responses:
        person = response.get("person", {})
        for email_record in person.get("emailAddresses", []):
            value = email_record.get("value")
            if isinstance(value, str):
                email_addresses.append(value)
    return normalize_email_addresses(email_addresses)


def build_people_service(
    *,
    oauth_client_id: str,
    oauth_client_secret: str,
    oauth_refresh_token: str,
) -> Any:
    """Build a Google People API service."""

    discovery = importlib.import_module("googleapiclient.discovery")
    credentials = build_oauth_credentials(
        client_id=oauth_client_id,
        client_secret=oauth_client_secret,
        refresh_token=oauth_refresh_token,
        scopes=[CONTACTS_READONLY_SCOPE],
    )
    return discovery.build("people", "v1", credentials=credentials, cache_discovery=False)


def fetch_group_member_resource_names(service: Any, resource_name: str, member_count: int) -> list[str]:
    """Fetch member resource names for one contact group."""

    response = (
        service.contactGroups()
        .get(
            resourceName=resource_name,
            maxMembers=max(member_count, 1),
            groupFields="name,memberCount,metadata",
        )
        .execute()
    )
    return list(response.get("memberResourceNames", []))


def fetch_people_email_addresses(service: Any, resource_names: Sequence[str]) -> list[str]:
    """Fetch email addresses for contact resource names."""

    responses: list[dict[str, Any]] = []
    for resource_name_batch in chunked(resource_names, MAX_BATCH_GET_PEOPLE):
        response = (
            service.people()
            .getBatchGet(
                resourceNames=list(resource_name_batch),
                personFields="emailAddresses",
            )
            .execute()
        )
        responses.extend(response.get("responses", []))
    return extract_email_addresses(responses)


class GoogleContactsAdapter(ContactsClient):
    """Google People API implementation of participant contact lookup."""

    def __init__(self, *, service: Any) -> None:
        self.service = service

    @classmethod
    def from_oauth(
        cls,
        *,
        oauth_client_id: str,
        oauth_client_secret: str,
        oauth_refresh_token: str,
    ) -> GoogleContactsAdapter:
        """Build a Google contacts adapter from OAuth user credentials."""

        return cls(
            service=build_people_service(
                oauth_client_id=oauth_client_id,
                oauth_client_secret=oauth_client_secret,
                oauth_refresh_token=oauth_refresh_token,
            )
        )

    def fetch_group_email_addresses(self, group_name: str) -> list[str]:
        """Fetch participant email addresses from the authorized user's contact group."""

        groups_response = (
            self.service.contactGroups()
            .list(pageSize=1000, groupFields="name,memberCount,metadata")
            .execute()
        )
        group = find_contact_group(groups_response.get("contactGroups", []), group_name)
        member_count = int(group.get("memberCount", 0))
        if member_count < 1:
            raise RuntimeError(f"Contact group has no members: {group_name}")

        resource_name = group.get("resourceName")
        if not isinstance(resource_name, str) or not resource_name:
            raise RuntimeError(f"Contact group is missing a resourceName: {group_name}")

        member_resource_names = fetch_group_member_resource_names(self.service, resource_name, member_count)
        if not member_resource_names:
            raise RuntimeError(f"Contact group has no member resource names: {group_name}")

        email_addresses = fetch_people_email_addresses(self.service, member_resource_names)
        if not email_addresses:
            raise RuntimeError(f"Contact group has no member email addresses: {group_name}")
        return email_addresses


def fetch_contact_group_email_addresses(
    *,
    oauth_client_id: str,
    oauth_client_secret: str,
    oauth_refresh_token: str,
    group_name: str,
) -> list[str]:
    """Fetch participant email addresses from the authorized user's contact group."""

    return GoogleContactsAdapter.from_oauth(
        oauth_client_id=oauth_client_id,
        oauth_client_secret=oauth_client_secret,
        oauth_refresh_token=oauth_refresh_token,
    ).fetch_group_email_addresses(group_name)
