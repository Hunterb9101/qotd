"""Keep Gherkin behavior tags and pytest coverage markers aligned."""

from __future__ import annotations

import ast
import re
from pathlib import Path


FEATURE_TAGS = re.compile(r"^((?:@[a-z0-9-]+ ?)+)\nFeature:", re.MULTILINE)


def _feature_tags() -> set[str]:
    tags: set[str] = set()
    specifications = sorted(Path("behaviors").glob("*.feature"))
    assert specifications, "Add at least one Gherkin behavior specification."

    for specification in specifications:
        match = FEATURE_TAGS.search(specification.read_text())
        assert match, f"Tag the Feature in {specification}."
        tags.update(match.group(1).removeprefix("@").split(" @"))

    return tags


def _behavior_markers() -> set[str]:
    markers: set[str] = set()
    for test_file in Path("tests").rglob("test_*.py"):
        tree = ast.parse(test_file.read_text(), filename=str(test_file))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                if not (
                    isinstance(decorator, ast.Call)
                    and isinstance(decorator.func, ast.Attribute)
                    and decorator.func.attr == "behavior"
                ):
                    continue
                markers.update(
                    argument.value
                    for argument in decorator.args
                    if isinstance(argument, ast.Constant)
                    and isinstance(argument.value, str)
                )
    return markers


def test_every_feature_tag_has_pytest_coverage() -> None:
    assert _feature_tags() <= _behavior_markers()


def test_every_behavior_marker_references_a_feature_tag() -> None:
    assert _behavior_markers() <= _feature_tags()
