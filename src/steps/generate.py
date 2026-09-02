"""
Step 4: write the copy.

This is the step that most needs a model and is most dangerous with one, so the
output is fenced on both sides:

  before - the model is told exactly which slots exist and their limits
  after  - slot names are validated, lengths are enforced in code, and empties
           are surfaced rather than filled

Character limits are enforced here rather than trusted to the prompt. Models are
approximately good at counting; the layout is not approximately sized.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..config import brand_rules, render_prompt, voice_guidance
from ..llm.client import BaseClient, LLMError
from ..models.brief import Brief
from .select import slot_limits


@dataclass
class GenerationResult:
    slots: dict[str, str]
    subject: str
    subject_options: list[str]
    preheader: str
    confidence: float
    empty_slots: list[str] = field(default_factory=list)
    truncated_slots: list[str] = field(default_factory=list)
    unknown_slots: list[str] = field(default_factory=list)
    model: str = "none"


class GenerationError(RuntimeError):
    pass


def generate_copy(brief: Brief, components: list[str], client: BaseClient) -> GenerationResult:
    wanted = _wanted_slots(components)
    limits = slot_limits(components)
    rules = brand_rules()

    prompt = render_prompt(
        "generate_copy",
        voice_guidance=voice_guidance(),
        banned_terms=rules.get("banned_terms", []),
        primary_message=brief.primary_message,
        audience=brief.audience,
        supporting_points="\n".join(f"- {p}" for p in brief.supporting_points),
        offer=brief.offer,
        cta_label=brief.cta_label,
        cta_url=brief.cta_url,
        event_name=brief.event_name,
        event_date=brief.event_date,
        event_time=brief.event_time,
        quote=brief.quote,
        attribution_name=brief.quote_attribution_name,
        attribution_role=brief.quote_attribution_role,
        event_duration=brief.event_duration,
        event_location=brief.event_location,
        resource_title=brief.resource_title,
        resource_url=brief.resource_url,
        image_url=brief.image_url,
        image_alt=brief.image_alt,
        slot_list=wanted,
        slot_limits="\n".join(f"{k}: max {v} chars" for k, v in limits.items()),
    )

    try:
        response = client.complete_json(
            prompt, schema_keys=["slots", "subject_options", "preheader"]
        )
    except LLMError:
        response = client.complete_json(
            prompt, schema_keys=["slots", "subject_options", "preheader"]
        )

    raw_slots = response.data.get("slots") or {}
    if not isinstance(raw_slots, dict):
        raise GenerationError("model returned non-object for slots")

    # Slots the model invented. Not silently dropped — reported and escalated.
    unknown = [k for k in raw_slots if k not in wanted]

    slots: dict[str, str] = {}
    truncated: list[str] = []
    for name in wanted:
        value = str(raw_slots.get(name, "") or "").strip()
        limit = limits.get(name)
        if limit and len(value) > limit:
            value = _truncate(value, limit)
            truncated.append(name)
        slots[name] = value

    # An empty OPTIONAL slot is fine — event_duration or a subhead simply
    # aren't in every brief. Only a required slot the brief can't fill is an
    # escalation. Treating all blanks the same would send perfectly good
    # emails back to the requester and train them to ignore the agent.
    required = _required_slots(components)
    empty = [k for k, v in slots.items() if not v and k in required]

    options = [str(s) for s in (response.data.get("subject_options") or []) if str(s).strip()]
    if not options:
        raise GenerationError("model returned no subject line options")

    subject = _pick_subject(options, rules)

    return GenerationResult(
        slots=slots,
        subject=subject,
        subject_options=options,
        preheader=str(response.data.get("preheader", "")).strip(),
        confidence=float(response.confidence),
        empty_slots=empty,
        truncated_slots=truncated,
        unknown_slots=unknown,
        model=response.model,
    )


def _required_slots(components: list[str]) -> set[str]:
    from ..config import component

    required: set[str] = set()
    for cid in components:
        required.update(component(cid).get("required") or [])
    return required


def _wanted_slots(components: list[str]) -> list[str]:
    from ..config import component

    slots: list[str] = []
    for cid in components:
        for slot in component(cid).get("slots") or []:
            if slot not in slots:
                slots.append(slot)
    return slots


def _truncate(value: str, limit: int) -> str:
    """Trim on a word boundary. Mid-word cuts read as a bug to the reader."""
    if len(value) <= limit:
        return value
    cut = value[:limit]
    if " " in cut:
        cut = cut[: cut.rfind(" ")]
    return cut.rstrip(" ,;:-")


def _pick_subject(options: list[str], rules: dict) -> str:
    """
    Deterministic choice among the model's options.

    Prefer one that already satisfies the length rule, so the linter is
    checking a genuine best effort rather than an arbitrary first pick.
    """
    lo = rules["subject_line"]["min_chars"]
    hi = rules["subject_line"]["max_chars"]
    for option in options:
        if lo <= len(option) <= hi and "!" not in option:
            return option
    return options[0]
