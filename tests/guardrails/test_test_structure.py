"""Guardrail requiring tests to mirror the application package structure."""

from __future__ import annotations

import fnmatch
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = PROJECT_ROOT / "qotd"
TESTS_ROOT = PROJECT_ROOT / "tests"

# Paths are relative to ``tests/``. Add narrowly-scoped exceptions here rather
# than weakening the matching rule for the rest of the suite.
TEST_STRUCTURE_IGNORES = (
    "acceptance/**", # Allows for behavioral tests tied to PRD requirements
    "guardrails/**",
)


def _is_ignored(path: Path) -> bool:
    relative_path = path.relative_to(TESTS_ROOT).as_posix()
    return any(fnmatch.fnmatch(relative_path, pattern) for pattern in TEST_STRUCTURE_IGNORES)


def _source_path_for_test(test_path: Path) -> Path:
    relative_path = test_path.relative_to(TESTS_ROOT)
    module_name = relative_path.name.removeprefix("test_")
    if module_name == "init.py":
        module_name = "__init__.py"
    return PACKAGE_ROOT / relative_path.parent / module_name


def test_tests_mirror_package_structure() -> None:
    """Every test module must sit beside the package path it exercises."""
    misplaced_tests = []
    for test_path in sorted(TESTS_ROOT.rglob("test_*.py")):
        if _is_ignored(test_path):
            continue
        expected_source = _source_path_for_test(test_path)
        if not expected_source.is_file():
            misplaced_tests.append(
                f"{test_path.relative_to(PROJECT_ROOT)} -> expected {expected_source.relative_to(PROJECT_ROOT)}"
            )

    assert not misplaced_tests, "Tests must mirror qotd's package structure:\n" + "\n".join(misplaced_tests)
