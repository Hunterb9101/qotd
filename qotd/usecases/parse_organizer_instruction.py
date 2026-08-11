"""Parse canonical Organizer Instructions from the initial email payload only."""

from __future__ import annotations

from dataclasses import dataclass


QUOTED_HISTORY_PREFIXES = (">", "on ", "from:", "-----original message-----")


@dataclass(frozen=True)
class OrganizerInstructionPayload:
    """A validated initial structured payload from an Organizer email."""

    action: str
    fields: dict[str, str]


def parse_organizer_instruction_payload(body_text: str) -> OrganizerInstructionPayload:
    """Parse only the first contiguous field block and reject duplicate fields."""

    fields: dict[str, str] = {}
    started = False
    for raw_line in body_text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw_line.strip()
        if not line and not started:
            continue
        if not line or line.casefold().startswith(QUOTED_HISTORY_PREFIXES):
            break
        if ":" not in line:
            raise ValueError("Organizer Instruction fields must use 'Name: value' lines")
        name, value = line.split(":", 1)
        key = name.strip().casefold()
        value = value.strip()
        if not key or not value:
            raise ValueError("Organizer Instruction fields must not be blank")
        if key in fields:
            raise ValueError(f"Organizer Instruction has duplicate field: {name.strip()}")
        fields[key] = value
        started = True

    action = fields.get("action", "").casefold()
    if not action:
        raise ValueError("Organizer Instruction Action is required")
    return OrganizerInstructionPayload(action=action, fields=fields)
