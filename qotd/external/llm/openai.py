"""OpenAI implementation of the provider-neutral LLM client."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jinja2 import Environment, StrictUndefined

from qotd.external.llm.core import TResponse
from qotd.external.openai_audit import now, record_openai_ai_call
from qotd.external.storage.canonical import CanonicalState


@dataclass(frozen=True)
class OpenAILLMClient:
    """Small wrapper around OpenAI Responses API structured JSON output."""

    client: Any
    model: str
    state: CanonicalState

    def create_structured_response(
        self,
        *,
        prompt_path: Path,
        payload: dict[str, Any],
        response_model: type[TResponse],
        schema_name: str,
        max_output_tokens: int,
        tools: tuple[dict[str, Any], ...] = (),
        use_case: str,
        usecase_run_id: str,
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
        started_at = now()
        response: Any = None
        error: Exception | None = None
        try:
            response = self.client.responses.create(**request)
            return response_model.model_validate(_parse_response_json(response))
        except Exception as exc:
            error = exc
            raise
        finally:
            record_openai_ai_call(
                state=self.state,
                use_case=use_case,
                prompt=prompt_path.stem,
                usecase_run_id=usecase_run_id,
                model=self.model,
                request=request,
                response=response,
                error=error,
                started_at=started_at,
                completed_at=now(),
            )


def build_openai_llm_client(
    *, api_key: str | None = None, model: str, state: CanonicalState
) -> OpenAILLMClient:
    """Build an OpenAI-backed provider-neutral LLM client."""

    from openai import OpenAI

    resolved_api_key = api_key or os.environ.get("OPENAI_API_KEY")
    if not resolved_api_key:
        raise ValueError("OPENAI_API_KEY is required for OpenAI LLM calls")
    return OpenAILLMClient(client=OpenAI(api_key=resolved_api_key), model=model, state=state)


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
