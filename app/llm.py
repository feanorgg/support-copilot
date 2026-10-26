"""Thin polza.ai client (OpenAI-compatible): JSON-schema chat completions + embeddings.

Every call returns an LLMCall with tokens, cost (polza reports RUB in usage.cost_rub) and
latency, so the pipeline and the eval can report cost per ticket from real billing data.
"""

from __future__ import annotations

import copy
import json
import time
from typing import TypeVar

import numpy as np
from openai import InternalServerError, OpenAI
from pydantic import BaseModel, ValidationError

from app.config import POLZA_API_KEY, POLZA_BASE_URL, PRICES_RUB_PER_M
from app.schemas import LLMCall

T = TypeVar("T", bound=BaseModel)

_client: OpenAI | None = None


class LLMError(RuntimeError):
    def __init__(self, message: str, call: LLMCall):
        super().__init__(message)
        self.call = call


def client() -> OpenAI:
    global _client
    if _client is None:
        if not POLZA_API_KEY:
            raise RuntimeError("POLZA_API_KEY is not set (copy .env.example to .env)")
        # The gateway can take minutes to answer. A client timeout shorter than that makes the SDK
        # resend a request that is still running (and still billed), so: long timeout, few retries.
        # Transient 503s (limitsCheckUnavailable) are handled by _create_with_gateway_retry.
        _client = OpenAI(base_url=POLZA_BASE_URL, api_key=POLZA_API_KEY, timeout=300, max_retries=2)
    return _client


def strict_schema(model: type[BaseModel]) -> dict:
    """Pydantic JSON schema -> OpenAI 'strict' flavour: refs inlined, every property required,
    additionalProperties false, no titles/defaults."""
    schema = model.model_json_schema()
    defs = schema.pop("$defs", {})

    def walk(node):
        if isinstance(node, dict):
            if "$ref" in node:
                return walk(copy.deepcopy(defs[node["$ref"].split("/")[-1]]))
            node = {k: walk(v) for k, v in node.items() if k not in ("title", "default")}
            if node.get("type") == "object" and "properties" in node:
                node["required"] = list(node["properties"])
                node["additionalProperties"] = False
            return node
        if isinstance(node, list):
            return [walk(x) for x in node]
        return node

    return walk(schema)


def _usage_to_call(stage: str, model: str, usage, latency_ms: int) -> LLMCall:
    call = LLMCall(stage=stage, model=model, latency_ms=latency_ms)
    if usage is None:
        return call
    u = usage.model_dump() if hasattr(usage, "model_dump") else dict(usage)
    call.prompt_tokens = u.get("prompt_tokens") or 0
    call.completion_tokens = u.get("completion_tokens") or 0
    call.cached_tokens = (u.get("prompt_tokens_details") or {}).get("cached_tokens") or 0
    cost = u.get("cost_rub", u.get("cost"))
    if cost is None:  # fall back to catalog prices if the gateway omitted cost
        p = PRICES_RUB_PER_M.get(model, {"in": 0, "out": 0})
        cost = (call.prompt_tokens * p["in"] + call.completion_tokens * p["out"]) / 1e6
    call.cost_rub = float(cost)
    return call


def chat_json(
    *,
    stage: str,
    model: str,
    system: str,
    user: str,
    schema: type[T],
    reasoning_effort: str | None = "none",
    max_tokens: int = 2000,
    temperature: float = 0.0,
) -> tuple[T, LLMCall]:
    """One chat completion constrained to `schema`. Retries once with the validation error
    fed back if the model returns JSON that does not validate. Raises LLMError (fail-closed)."""
    # Not using provider.require_parameters: combined with temperature + reasoning it 400s on
    # polza; json_schema support was checked against the model catalog instead.
    extra_body: dict = {}
    if reasoning_effort:
        extra_body["reasoning"] = {"effort": reasoning_effort}
    response_format = {
        "type": "json_schema",
        "json_schema": {"name": schema.__name__, "strict": True, "schema": strict_schema(schema)},
    }
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    calls: list[LLMCall] = []

    for attempt in range(2):
        t0 = time.perf_counter()
        try:
            resp = _create_with_gateway_retry(
                model=model,
                messages=messages,
                response_format=response_format,
                max_tokens=max_tokens,
                temperature=temperature,
                extra_body=extra_body,
            )
        except Exception as exc:  # network / 4xx / 5xx after SDK retries
            call = LLMCall(stage=stage, model=model, latency_ms=int((time.perf_counter() - t0) * 1000), error=str(exc)[:500])
            raise LLMError(f"{stage}: request failed: {exc}", _merge(calls + [call])) from exc

        call = _usage_to_call(stage, model, resp.usage, int((time.perf_counter() - t0) * 1000))
        calls.append(call)
        content = resp.choices[0].message.content or ""
        try:
            return schema.model_validate(json.loads(_strip_fences(content))), _merge(calls)
        except (json.JSONDecodeError, ValidationError) as exc:
            if attempt == 1:
                call.error = f"invalid JSON: {exc}"[:500]
                raise LLMError(f"{stage}: invalid JSON after retry", _merge(calls)) from exc
            messages = messages + [
                {"role": "assistant", "content": content},
                {"role": "user", "content": f"That output did not match the schema: {exc}. Return only valid JSON."},
            ]
    raise AssertionError("unreachable")


GATEWAY_RETRY_WAITS_S = (15, 30)


def _create_with_gateway_retry(**kwargs):
    """The SDK already retries 5xx with short backoff; polza's 503 limitsCheckUnavailable can
    last longer, so wait it out twice more before failing closed."""
    for wait in (*GATEWAY_RETRY_WAITS_S, None):
        try:
            return client().chat.completions.create(**kwargs)
        except InternalServerError:
            if wait is None:
                raise
            time.sleep(wait)


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        text = text.rsplit("```", 1)[0]
    return text


def _merge(calls: list[LLMCall]) -> LLMCall:
    if len(calls) == 1:
        return calls[0]
    first = calls[0]
    return LLMCall(
        stage=first.stage,
        model=first.model,
        prompt_tokens=sum(c.prompt_tokens for c in calls),
        completion_tokens=sum(c.completion_tokens for c in calls),
        cached_tokens=sum(c.cached_tokens for c in calls),
        cost_rub=sum(c.cost_rub for c in calls),
        latency_ms=sum(c.latency_ms for c in calls),
        error="; ".join(c.error for c in calls if c.error) or None,
    )


def key_budget() -> dict:
    """polza key limits: {'limit', 'limit_remaining', 'limit_reset', 'usage_daily', ...} in RUB."""
    import requests

    resp = requests.get(f"{POLZA_BASE_URL}/key", headers={"Authorization": f"Bearer {POLZA_API_KEY}"}, timeout=60)
    resp.raise_for_status()
    return resp.json()


def embed(texts: list[str], model: str, stage: str = "embed") -> tuple[np.ndarray, LLMCall]:
    t0 = time.perf_counter()
    resp = client().embeddings.create(model=model, input=texts)
    call = _usage_to_call(stage, model, resp.usage, int((time.perf_counter() - t0) * 1000))
    vecs = np.array([d.embedding for d in sorted(resp.data, key=lambda d: d.index)], dtype=np.float32)
    vecs /= np.linalg.norm(vecs, axis=1, keepdims=True)
    return vecs, call
