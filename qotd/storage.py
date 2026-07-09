"""Persistent JSONL state for QOTD records."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from qotd.models import StoredQuestion


def append_question_record(path: Path, record: StoredQuestion) -> None:
    """Append one question record to a JSONL state file."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as state_file:
        state_file.write(json.dumps(record.to_json_dict(), sort_keys=True) + "\n")


def read_question_records(path: Path) -> list[dict[str, Any]]:
    """Read question records from JSONL state."""

    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            records.append(json.loads(line))
    return records

