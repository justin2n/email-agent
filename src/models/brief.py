"""
The brief contract. Everything downstream depends on this shape.

DELIBERATE DESIGN CHOICE
------------------------
Completeness is decided HERE, in code, not by the model. "Is this brief
missing a CTA?" is a schema check, not a judgment call. The model is used
to *extract* fields from messy text and to *phrase* the follow-up question,
but never to decide whether the brief is good enough to proceed.

PORTABILITY
-----------
Implemented with stdlib dataclasses so the pipeline runs with zero
dependencies. `to_pydantic_schema()` emits the same contract as JSON Schema
for the production Pydantic v2 model (see briefs/schema.json). Swapping in
Pydantic is a drop-in: the field names, requirements and validators below
are the source of truth for both.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field, fields
from datetime import date, datetime
from typing import Any


CAMPAIGN_TYPES = [
    "product_launch",
    "feature_announcement",
    "webinar_invite",
    "webinar_reminder",
    "nurture_education",
    "customer_story",
    "event_followup",
    "newsletter",
]

AUDIENCES = [
    "designers",
    "developers",
    "design_leaders",
    "educators",
    "students",
    "enterprise_it",
    "all_users",
    "trial_users",
    "churned_users",
]

URL_RE = re.compile(r"^https://[^\s<>\"]+$")


@dataclass
class ValidationIssue:
    field: str
    code: str
    message: str

    def __str__(self) -> str:  # pragma: no cover - display only
        return f"{self.field}: {self.message}"


@dataclass
class Brief:
    """A marketing email request, structured."""

    # --- required for any email to be built ---
    campaign_type: str | None = None
    audience: str | None = None
    primary_message: str | None = None
    cta_label: str | None = None
    cta_url: str | None = None
    send_window: str | None = None

    # --- optional, campaign-type dependent ---
    supporting_points: list[str] = field(default_factory=list)
    offer: str | None = None
    event_name: str | None = None
    event_date: str | None = None
    event_time: str | None = None
    event_duration: str | None = None
    event_location: str | None = None
    quote: str | None = None
    quote_attribution_name: str | None = None
    quote_attribution_role: str | None = None
    resource_title: str | None = None
    resource_url: str | None = None
    image_url: str | None = None
    image_alt: str | None = None
    provided_copy: str | None = None

    # --- provenance ---
    requester: str | None = None
    raw_request: str | None = None
    source: str = "cli"

    # Fields required regardless of campaign type.
    BASE_REQUIRED = (
        "campaign_type",
        "audience",
        "primary_message",
        "cta_label",
        "cta_url",
        "send_window",
    )

    # Additional requirements that depend on campaign type. This is why
    # completeness cannot be a flat "are all fields present" check.
    CONDITIONAL_REQUIRED: dict[str, tuple[str, ...]] = None  # set below

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------
    def required_fields(self) -> tuple[str, ...]:
        req = list(self.BASE_REQUIRED)
        req += list(CONDITIONAL_REQUIRED.get(self.campaign_type or "", ()))
        return tuple(dict.fromkeys(req))

    def missing_fields(self) -> list[str]:
        """Deterministic. This is the gate — never a model decision."""
        missing = []
        for name in self.required_fields():
            value = getattr(self, name, None)
            if value is None or (isinstance(value, str) and not value.strip()):
                missing.append(name)
        return missing

    def validate(self) -> list[ValidationIssue]:
        """Field-level checks beyond mere presence."""
        issues: list[ValidationIssue] = []

        if self.campaign_type and self.campaign_type not in CAMPAIGN_TYPES:
            issues.append(ValidationIssue(
                "campaign_type", "unknown_value",
                f"'{self.campaign_type}' is not a known campaign type",
            ))

        if self.audience and self.audience not in AUDIENCES:
            issues.append(ValidationIssue(
                "audience", "unknown_value",
                f"'{self.audience}' is not a known audience",
            ))

        for url_field in ("cta_url", "resource_url", "image_url"):
            value = getattr(self, url_field)
            if value and not URL_RE.match(value):
                issues.append(ValidationIssue(
                    url_field, "bad_url",
                    "must be an absolute https:// URL",
                ))

        if self.event_date:
            parsed = _parse_date(self.event_date)
            if parsed is None:
                issues.append(ValidationIssue(
                    "event_date", "unparseable_date",
                    f"could not read '{self.event_date}' as a date",
                ))
            elif parsed < date.today():
                issues.append(ValidationIssue(
                    "event_date", "date_in_past",
                    f"{self.event_date} is in the past",
                ))

        if self.quote and not self.quote_attribution_name:
            issues.append(ValidationIssue(
                "quote_attribution_name", "missing_attribution",
                "a quote cannot ship without attribution",
            ))

        return issues

    def is_complete(self) -> bool:
        return not self.missing_fields() and not self.validate()

    # ------------------------------------------------------------------
    # Grounding support
    # ------------------------------------------------------------------
    def grounding_corpus(self) -> str:
        """
        Every piece of text the requester actually supplied.

        The generated email is checked against this. Anything asserted in the
        output that has no basis here is treated as invented.
        """
        parts: list[str] = []
        for f in fields(self):
            value = getattr(self, f.name)
            if isinstance(value, str) and value:
                parts.append(value)
            elif isinstance(value, list):
                parts.extend(str(v) for v in value)
        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Brief":
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)


CONDITIONAL_REQUIRED: dict[str, tuple[str, ...]] = {
    "webinar_invite": ("event_name", "event_date", "event_time"),
    "webinar_reminder": ("event_name", "event_date", "event_time"),
    "customer_story": ("quote", "quote_attribution_name"),
    "nurture_education": ("resource_title", "resource_url"),
    "event_followup": ("resource_title", "resource_url"),
}
Brief.CONDITIONAL_REQUIRED = CONDITIONAL_REQUIRED


_DATE_FORMATS = (
    "%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d %B %Y", "%B %d, %Y",
    "%b %d, %Y", "%d %b %Y",
)


def _parse_date(value: str) -> date | None:
    value = value.strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


# Human-readable labels used when asking the requester for a missing field.
FIELD_LABELS = {
    "campaign_type": "what kind of email this is",
    "audience": "who it's going to",
    "primary_message": "the single main thing you want to say",
    "cta_label": "what the button should say",
    "cta_url": "where the button should go",
    "send_window": "when it needs to go out",
    "event_name": "the event name",
    "event_date": "the event date",
    "event_time": "the event time (with time zone)",
    "quote": "the approved customer quote",
    "quote_attribution_name": "who the quote is from",
    "resource_title": "the name of the resource you're linking to",
    "resource_url": "the link to the resource",
}
