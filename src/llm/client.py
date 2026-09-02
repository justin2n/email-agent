"""
The only place the pipeline talks to a model.

Two backends behind one interface:

  AnthropicClient  - the real thing. Needs ANTHROPIC_API_KEY and the SDK.
  StubClient       - deterministic canned responses, no network.

This seam is not a testing convenience bolted on afterwards. It is the
architecture: because every model call returns structured data against a
known schema, the model can be replaced by a fixture and the entire rest
of the pipeline — selection, assembly, linting, escalation — runs
unchanged and its tests still pass.

If swapping the model out breaks your pipeline, too much of your logic
was living inside the prompt.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from typing import Any


DEFAULT_MODEL = "claude-sonnet-4-6"
CHEAP_MODEL = "claude-haiku-4-5-20251001"


@dataclass
class LLMResponse:
    data: dict[str, Any]
    raw: str
    model: str
    backend: str
    input_tokens: int = 0
    output_tokens: int = 0
    confidence: float = 1.0
    notes: list[str] = field(default_factory=list)


class LLMError(RuntimeError):
    """Raised when the model returns something unusable. Never swallowed."""


class BaseClient:
    backend = "base"

    def complete_json(
        self,
        prompt: str,
        *,
        schema_keys: list[str],
        model: str = DEFAULT_MODEL,
        max_tokens: int = 1500,
    ) -> LLMResponse:
        raise NotImplementedError

    @staticmethod
    def _parse_json(text: str, schema_keys: list[str]) -> dict[str, Any]:
        """
        Strict parse. We do not 'repair' model output beyond stripping code
        fences — a response we had to guess at is a response we cannot trust,
        and the caller's retry-then-escalate path is the correct handling.
        """
        cleaned = text.strip()
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise LLMError(f"model did not return valid JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise LLMError("model returned JSON but not an object")
        missing = [k for k in schema_keys if k not in data]
        if missing:
            raise LLMError(f"model response missing required keys: {missing}")
        return data


class AnthropicClient(BaseClient):
    """Production backend. Requires `pip install anthropic` and an API key."""

    backend = "anthropic"

    def __init__(self, api_key: str | None = None):
        try:
            import anthropic  # noqa: F401
        except ImportError as exc:  # pragma: no cover
            raise LLMError(
                "anthropic SDK not installed. `pip install anthropic`, "
                "or run with LLM_BACKEND=stub for the offline pipeline."
            ) from exc
        import anthropic

        key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise LLMError("ANTHROPIC_API_KEY is not set")
        self._client = anthropic.Anthropic(api_key=key)

    def complete_json(
        self,
        prompt: str,
        *,
        schema_keys: list[str],
        model: str = DEFAULT_MODEL,
        max_tokens: int = 1500,
    ) -> LLMResponse:
        msg = self._client.messages.create(
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
        data = self._parse_json(text, schema_keys)
        return LLMResponse(
            data=data,
            raw=text,
            model=model,
            backend=self.backend,
            input_tokens=getattr(msg.usage, "input_tokens", 0),
            output_tokens=getattr(msg.usage, "output_tokens", 0),
            confidence=float(data.get("_confidence", 1.0)),
        )


class StubClient(BaseClient):
    """
    Offline backend. Deterministic, seeded from the prompt hash so the same
    input always yields the same output — which is what makes the eval suite
    reproducible without burning tokens.

    Responses are keyed by the step marker each prompt carries.
    """

    backend = "stub"

    def __init__(self, fixtures: dict[str, Any] | None = None):
        self.fixtures = fixtures or {}

    def complete_json(
        self,
        prompt: str,
        *,
        schema_keys: list[str],
        model: str = DEFAULT_MODEL,
        max_tokens: int = 1500,
    ) -> LLMResponse:
        from .stub_responses import respond

        step = _step_marker(prompt)
        data = respond(step, prompt, self.fixtures)
        missing = [k for k in schema_keys if k not in data]
        if missing:
            raise LLMError(f"stub response missing required keys: {missing}")
        raw = json.dumps(data)
        return LLMResponse(
            data=data,
            raw=raw,
            model=f"stub:{model}",
            backend=self.backend,
            input_tokens=len(prompt) // 4,
            output_tokens=len(raw) // 4,
            confidence=float(data.get("_confidence", 0.9)),
        )


def _step_marker(prompt: str) -> str:
    m = re.search(r"<step>([a-z_]+)</step>", prompt)
    return m.group(1) if m else "unknown"


def get_client(backend: str | None = None) -> BaseClient:
    """
    Backend selection. Defaults to stub so a fresh clone runs immediately
    with no key and no network.
    """
    backend = (backend or os.environ.get("LLM_BACKEND") or "stub").lower()
    if backend == "anthropic":
        return AnthropicClient()
    if backend == "stub":
        return StubClient()
    raise LLMError(f"unknown LLM_BACKEND '{backend}' (expected 'anthropic' or 'stub')")


def prompt_fingerprint(prompt: str) -> str:
    """Recorded in traces so a run can be tied to an exact prompt version."""
    return hashlib.sha256(prompt.encode()).hexdigest()[:12]
