"""Google Contacts lookup for QOTD participants."""

from __future__ import annotations

import importlib
from collections.abc import Iterable, Sequence
from typing import Any


CONTACTS_READONLY_SCOPE = "https://www.googleapis.com/auth/contacts.readonly"
MAX_BATCH_GET_PEOPLE = 200


def normalize_email_addresses(email_addresses: Iterable[str]) -> list[str]:
    """Normalize, dedupe, and sort email addresses."""

    normalized = {
        email_address.strip().lower()
        for email_address in email_addresses
        if email_address.strip()
    }
    return sorted(normalized)


def find_contact_group(contact_groups: Sequence[dict[str, Any]], group_name: str) -> dict[str, Any]:
    """Find one contact group by exact display name."""

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


def chunked(values: Sequence[str], size: int) -> Iterable[Sequence[str]]:
    """Yield fixed-size chunks from a sequence."""

    for index in range(0, len(values), size):
        yield values[index : index + size]


def build_people_service(*, delegated_user: str, service_account_file: str) -> Any:
    """Build a delegated Google People API service."""

    service_account = importlib.import_module("google.oauth2.service_account")
    discovery = importlib.import_module("googleapiclient.discovery")

    credentials = service_account.Credentials.from_service_account_file(
        service_account_file,
        scopes=[CONTACTS_READONLY_SCOPE],
    ).with_subject(delegated_user)
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


def fetch_contact_group_email_addresses(
    *,
    delegated_user: str,
    service_account_file: str,
    group_name: str,
) -> list[str]:
    """Fetch participant email addresses from a delegated user's contact group."""

    service = build_people_service(
        delegated_user=delegated_user,
        service_account_file=service_account_file,
    )
    groups_response = (
        service.contactGroups()
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

    member_resource_names = fetch_group_member_resource_names(service, resource_name, member_count)
    if not member_resource_names:
        raise RuntimeError(f"Contact group has no member resource names: {group_name}")

    email_addresses = fetch_people_email_addresses(service, member_resource_names)
    if not email_addresses:
        raise RuntimeError(f"Contact group has no member email addresses: {group_name}")
    return email_addresses

