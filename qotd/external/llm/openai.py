"""OpenAI implementation of the provider-neutral LLM client."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, StrictUndefined

from qotd.external.llm.core import TResponse
from qotd.domain.canonical import AICall, new_id
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
        started_at = datetime.now(UTC)
        response: Any = None
        error: Exception | None = None
        try:
            response = self.client.responses.create(**request)
            return response_model.model_validate(_parse_response_json(response))
        except Exception as exc:
            error = exc
            raise
        finally:
            completed_at = datetime.now(UTC)
            self.state.record_ai_call(
                AICall(
                    id=new_id(),
                    use_case=use_case,
                    prompt=prompt_path.stem,
                    usecase_run_id=usecase_run_id,
                    provider="openai",
                    model=self.model,
                    request=_sanitize(request),
                    response=_sanitize(_to_json_dict(response)) if response is not None else None,
                    provider_request_id=_provider_request_id(response),
                    status="failed" if error is not None else "succeeded",
                    error_type=type(error).__name__ if error is not None else None,
                    error_message=str(error) if error is not None else None,
                    started_at=started_at,
                    completed_at=completed_at,
                    latency_ms=round((completed_at - started_at).total_seconds() * 1000),
                    **_usage(response),
                )
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


def _to_json_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return value
    if hasattr(value, "__dict__"):
        return dict(vars(value))
    return {"value": str(value)}


def _sanitize(value: Any) -> Any:
    """Return a JSON-compatible value while removing credentials."""

    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if key.casefold() in {"api_key", "authorization", "x_api_key"} else _sanitize(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_sanitize(item) for item in value]
    if hasattr(value, "model_dump"):
        return _sanitize(value.model_dump(mode="json"))
    if hasattr(value, "__dict__"):
        return _sanitize(vars(value))
    return value


def _provider_request_id(response: Any) -> str | None:
    request_id = getattr(response, "_request_id", None) or getattr(response, "request_id", None)
    return str(request_id) if request_id is not None else None


def _usage(response: Any) -> dict[str, int | None]:
    usage = getattr(response, "usage", None)
    return {
        "input_tokens": getattr(usage, "input_tokens", None),
        "output_tokens": getattr(usage, "output_tokens", None),
        "total_tokens": getattr(usage, "total_tokens", None),
    }
