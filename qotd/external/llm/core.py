"""Provider-neutral LLM client contracts."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel


TResponse = TypeVar("TResponse", bound=BaseModel)


class LLMClient(Protocol):
    """Provider-neutral structured-output LLM client."""

    def create_structured_response(
        self,
        *,
        prompt_path: Path,
        payload: dict[str, Any],
        response_model: type[TResponse],
        schema_name: str,
        max_output_tokens: int,
    ) -> TResponse:
        """Return validated structured output from an LLM provider."""
