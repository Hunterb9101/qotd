"""Template rendering helpers for presentation content."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined


_TEMPLATE_DIR = Path(__file__).with_name("templates")


def template_environment() -> Environment:
    """Build the presentation template environment."""

    return Environment(
        loader=FileSystemLoader(_TEMPLATE_DIR),
        autoescape=False,
        keep_trailing_newline=False,
        lstrip_blocks=True,
        trim_blocks=True,
        undefined=StrictUndefined,
    )


def render_template(template_name: str, **context: Any) -> str:
    """Render a presentation template with strict context validation."""

    return template_environment().get_template(template_name).render(**context).strip()
