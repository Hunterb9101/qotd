"""Guardrail preventing imports across explicitly forbidden boundaries."""

from __future__ import annotations

import ast
import fnmatch
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = PROJECT_ROOT / "qotd"

# Paths are relative to ``qotd/``.
IMPORT_GUARDRAIL_IGNORES: tuple[str, ...] = ()

# Keys match importing modules and values match modules they may not import.
# These are ordinary fnmatch patterns; keep architectural meaning in module
# placement instead of adding special cases to the matching language.
FORBIDDEN_IMPORTS = {
    "qotd.domain.*": (
        "qotd.external.*",
        "qotd.presentation.*",
        "qotd.usecases.*",
    ),
    "qotd.usecases.*": (
        "qotd.external.contacts.google",
        "qotd.external.email.gmail",
        "qotd.external.llm.openai",
        "qotd.external.storage.bigquery",
        "qotd.external.web_search.openai",
        "qotd.presentation.*",
    ),
    "qotd.external.*.core": (
        "qotd.external.auth.*",
    ),
}


def _is_ignored(path: Path) -> bool:
    relative_path = path.relative_to(PACKAGE_ROOT).as_posix()
    return any(fnmatch.fnmatch(relative_path, pattern) for pattern in IMPORT_GUARDRAIL_IGNORES)


def _qotd_imports(source_path: Path) -> set[str]:
    tree = ast.parse(source_path.read_text(), filename=str(source_path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names if alias.name.startswith("qotd"))
        elif isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("qotd"):
            imports.add(node.module)
    return imports


def _is_forbidden_import(source_module: str, imported_module: str) -> bool:
    return any(
        fnmatch.fnmatch(source_module, source_pattern)
        and any(fnmatch.fnmatch(imported_module, pattern) for pattern in imported_patterns)
        for source_pattern, imported_patterns in FORBIDDEN_IMPORTS.items()
    )


@pytest.mark.parametrize(
    "source_path",
    [path for path in sorted(PACKAGE_ROOT.rglob("*.py")) if not _is_ignored(path)],
    ids=lambda path: str(path.relative_to(PROJECT_ROOT)),
)
def test_imports_do_not_cross_forbidden_boundaries(source_path: Path) -> None:
    """Package imports must not cross a declared forbidden boundary."""
    source_module = ".".join(source_path.relative_to(PROJECT_ROOT).with_suffix("").parts)
    violations = [
        imported_module
        for imported_module in sorted(_qotd_imports(source_path))
        if _is_forbidden_import(source_module, imported_module)
    ]

    assert not violations, f"{source_module} has forbidden imports: {', '.join(violations)}"
