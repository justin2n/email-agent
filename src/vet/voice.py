"""
Step 6b: the tone assessment.

The only genuinely judgment-based check in the pipeline. Everything mechanical
has already been decided by rules; this is the part that cannot be.

Note what this step does NOT do: it does not decide whether the email ships.
It returns scores and citations, and `escalate.decide()` applies the thresholds.
Keeping scoring and deciding separate means the thresholds are testable without
a model in the loop, and adjustable without touching a prompt.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..config import render_prompt, voice_guidance
from ..llm.client import BaseClient, LLMError
from .lint import _visible_text

DIMENSIONS = ("plainness", "directness", "specificity", "register_fit", "restraint")


@dataclass
class VoiceResult:
    scores: dict[str, int] = field(default_factory=dict)
    citations: dict[str, str] = field(default_factory=dict)
    mean: float = 0.0
    confidence: float = 0.0
    available: bool = True
    model: str = "none"

    def to_dict(self) -> dict:
        return {
            "scores": self.scores,
            "citations": self.citations,
            "mean": self.mean,
            "confidence": self.confidence,
            "available": self.available,
        }


def vet_voice(html: str, subject: str, preheader: str, audience: str | None,
              client: BaseClient) -> VoiceResult:
    copy = f"Subject: {subject}\nPreheader: {preheader}\n\n{_visible_text(html)}"

    prompt = render_prompt(
        "vet_voice",
        voice_guidance=voice_guidance(),
        audience=audience or "all_users",
        email_copy=copy,
    )

    try:
        response = client.complete_json(prompt, schema_keys=["scores", "mean"])
    except LLMError:
        # A failed tone check is not a pass. It is an unknown, and unknowns
        # go to a human rather than through.
        return VoiceResult(available=False, model="unavailable")

    raw_scores = response.data.get("scores") or {}
    scores = {}
    for dimension in DIMENSIONS:
        try:
            scores[dimension] = int(raw_scores.get(dimension, 0))
        except (TypeError, ValueError):
            scores[dimension] = 0

    mean = sum(scores.values()) / len(scores) if scores else 0.0

    return VoiceResult(
        scores=scores,
        citations={str(k): str(v) for k, v in (response.data.get("citations") or {}).items()},
        mean=round(mean, 2),
        confidence=float(response.confidence),
        available=True,
        model=response.model,
    )
