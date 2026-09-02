"""
Step 3: choose the component sequence.

Rules first. The manifest maps campaign type to a fixed sequence, and that
covers the overwhelming majority of real requests. The model is consulted only
when no mapping exists.

This ordering is the point. Most of what looks like it needs AI is a lookup
someone never got round to writing down. Every request that resolves by rule is
one that costs nothing, cannot hallucinate, and returns the same answer every
time.

The path taken is recorded, so we can watch the rule/model ratio over time. If
the model path starts firing often, that is a signal to add a sequence — not to
improve the prompt.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..config import component, component_ids, manifest, render_prompt, sequence_for
from ..llm.client import BaseClient, LLMError
from ..models.brief import Brief


@dataclass
class SelectionResult:
    components: list[str]
    path: str            # "rule" | "model"
    reasoning: str
    confidence: float
    model: str = "none"


class SelectionError(RuntimeError):
    """Selection produced something outside the closed vocabulary."""


def select_components(brief: Brief, client: BaseClient) -> SelectionResult:
    sequence = sequence_for(brief.campaign_type)
    if sequence:
        return SelectionResult(
            components=_validate(sequence),
            path="rule",
            reasoning=f"Deterministic sequence for campaign_type '{brief.campaign_type}'.",
            confidence=1.0,
        )
    return _model_fallback(brief, client)


def _model_fallback(brief: Brief, client: BaseClient) -> SelectionResult:
    allowed = component_ids()
    reference = "\n".join(
        f"- {cid}: {spec['purpose']} (slots: {', '.join(spec.get('slots') or []) or 'none'})"
        for cid, spec in manifest()["components"].items()
    )
    prompt = render_prompt(
        "select_components",
        allowed_components=allowed,
        component_reference=reference,
        brief_json=brief.to_json(),
    )

    try:
        response = client.complete_json(prompt, schema_keys=["components"])
    except LLMError as exc:
        raise SelectionError(f"component selection failed: {exc}") from exc

    picked = [str(c) for c in response.data.get("components", [])]
    return SelectionResult(
        components=_validate(picked),
        path="model",
        reasoning=str(response.data.get("reasoning", "")),
        confidence=float(response.confidence),
        model=response.model,
    )


def _validate(components: list[str]) -> list[str]:
    """
    The closed-vocabulary check.

    An unknown id raises rather than being dropped. Silently removing a component
    the model asked for would produce a quietly wrong email, which is exactly the
    failure mode this whole design exists to prevent.
    """
    known = set(component_ids())
    unknown = [c for c in components if c not in known]
    if unknown:
        raise SelectionError(
            f"components not in manifest: {unknown}. "
            f"This escalates rather than being silently dropped."
        )

    if not components:
        raise SelectionError("no components selected")

    # Structural invariants that hold regardless of who chose the sequence.
    if components.count("cta_button") > 1:
        raise SelectionError("more than one primary CTA selected")

    mandatory = [
        cid for cid, spec in manifest()["components"].items()
        if spec.get("mandatory")
    ]
    result = list(components)
    for cid in mandatory:
        if cid not in result:
            result.append(cid)
        elif result[-1] != cid:
            result.remove(cid)
            result.append(cid)
    return result


def required_slots(components: list[str]) -> list[str]:
    slots: list[str] = []
    for cid in components:
        for slot in component(cid).get("slots") or []:
            if slot not in slots:
                slots.append(slot)
    return slots


def slot_limits(components: list[str]) -> dict[str, int]:
    limits: dict[str, int] = {}
    for cid in components:
        for slot, limit in (component(cid).get("limits") or {}).items():
            limits[slot] = min(limit, limits.get(slot, limit))
    return limits


def unfillable(components: list[str], brief: Brief) -> list[str]:
    """
    Components whose required slots the brief cannot support.

    Checked before generation so we fail on a missing quote rather than
    inviting the model to write one.
    """
    data = brief.to_dict()
    hints = {
        "quote": "quote",
        "attribution_name": "quote_attribution_name",
        "resource_title": "resource_title",
        "resource_url": "resource_url",
        "resource_label": "resource_title",
        "event_name": "event_name",
        "event_date": "event_date",
        "event_time": "event_time",
        "image_url": "image_url",
        "image_alt": "image_alt",
    }
    problems = []
    for cid in components:
        for slot in component(cid).get("required") or []:
            source = hints.get(slot)
            if source and not data.get(source):
                problems.append(f"{cid} needs {slot}, brief has no {source}")
    return problems
