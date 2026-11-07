"""Durable accounting for OpenAI Responses API calls."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from qotd.domain.canonical import AICall, new_id
from qotd.external.storage.canonical import CanonicalState


def record_openai_ai_call(
    *,
    state: CanonicalState,
    use_case: str,
    prompt: str,
    usecase_run_id: str,
    model: str,
    request: dict[str, Any],
    response: Any,
    error: Exception | None,
    started_at: datetime,
    completed_at: datetime,
) -> None:
    """Persist one OpenAI request and its returned usage metadata."""

    state.record_ai_call(
        AICall(
            id=new_id(),
            use_case=use_case,
            prompt=prompt,
            usecase_run_id=usecase_run_id,
            provider="openai",
            model=model,
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
            web_search_calls=_web_search_call_count(response),
        )
    )


def now() -> datetime:
    """Return the current UTC time for AI Call accounting."""

    return datetime.now(UTC)


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
    input_token_details = getattr(usage, "input_tokens_details", None)
    return {
        "input_tokens": getattr(usage, "input_tokens", None),
        "cached_input_tokens": getattr(input_token_details, "cached_tokens", None),
        "output_tokens": getattr(usage, "output_tokens", None),
        "total_tokens": getattr(usage, "total_tokens", None),
    }


def _web_search_call_count(response: Any) -> int:
    return sum(
        getattr(item, "type", None) == "web_search_call"
        for item in getattr(response, "output", ()) or ()
    )
