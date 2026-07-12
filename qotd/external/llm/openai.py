"""OpenAI implementation of the provider-neutral LLM client."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jinja2 import Environment, StrictUndefined

from qotd.external.llm.core import TResponse


@dataclass(frozen=True)
class OpenAILLMClient:
    """Small wrapper around OpenAI Responses API structured JSON output."""

    client: Any
    model: str

    def create_structured_response(
        self,
        *,
        prompt_path: Path,
        payload: dict[str, Any],
        response_model: type[TResponse],
        schema_name: str,
        max_output_tokens: int,
        tools: tuple[dict[str, Any], ...] = (),
    ) -> TResponse:
        """Call OpenAI and parse the response into a Pydantic model."""

        request: dict[str, Any] = {
            "model": self.model,
            "instructions": render_prompt(prompt_path, payload),
            "input": "Return the requested structured result.",
            "max_output_tokens": max_output_tokens,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": schema_name,
                    "schema": response_model.model_json_schema(),
                    "strict": True,
                }
            },
        }
        if tools:
            request["tools"] = list(tools)
        response = self.client.responses.create(
            **request,
        )
        return response_model.model_validate(_parse_response_json(response))


def build_openai_llm_client(*, api_key: str | None = None, model: str) -> OpenAILLMClient:
    """Build an OpenAI-backed provider-neutral LLM client."""

    from openai import OpenAI

    resolved_api_key = api_key or os.environ.get("OPENAI_API_KEY")
    if not resolved_api_key:
        raise ValueError("OPENAI_API_KEY is required for OpenAI LLM calls")
    return OpenAILLMClient(client=OpenAI(api_key=resolved_api_key), model=model)


def load_prompt(prompt_path: Path) -> str:
    """Read a markdown prompt file."""

    return prompt_path.read_text(encoding="utf-8")


def render_prompt(prompt_path: Path, payload: dict[str, Any]) -> str:
    """Render a Jinja prompt template using the structured request payload."""

    environment = Environment(
        autoescape=False,
        keep_trailing_newline=True,
        undefined=StrictUndefined,
    )
    return environment.from_string(load_prompt(prompt_path)).render(**payload)


def _parse_response_json(response: Any) -> Any:
    output_text = getattr(response, "output_text", None)
    if isinstance(output_text, str) and output_text.strip():
        return json.loads(output_text)
    return _parse_response_output(response)


def _parse_response_output(response: Any) -> Any:
    output = getattr(response, "output", None)
    if not output:
        raise ValueError("OpenAI response did not include output text")
    for item in output:
        for content in getattr(item, "content", []) or []:
            text = getattr(content, "text", None)
            if isinstance(text, str) and text.strip():
                return json.loads(text)
    raise ValueError("OpenAI response did not include parseable JSON text")
