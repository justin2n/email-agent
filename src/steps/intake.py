"""
Steps 1-2: free text in, validated brief out.

The split of responsibility here is the whole design in miniature:

  model  -> reads the messy request, pulls out fields
  code   -> decides whether what came back is usable
  code   -> decides which fields are still missing
  model  -> phrases the questions that close those gaps

The model never gets to declare a brief complete.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..config import render_prompt
from ..llm.client import BaseClient, LLMError, CHEAP_MODEL
from ..models.brief import AUDIENCES, CAMPAIGN_TYPES, Brief, FIELD_LABELS

EXTRACT_KEYS = ["campaign_type", "audience", "primary_message", "_confidence"]

# Below this, we do not trust the extraction enough to build on it.
MIN_EXTRACTION_CONFIDENCE = 0.7


@dataclass
class ExtractionResult:
    brief: Brief
    confidence: float
    retried: bool
    raw: str
    model: str


def extract_brief(
    raw_request: str,
    client: BaseClient,
    *,
    requester: str | None = None,
    source: str = "cli",
) -> ExtractionResult:
    """
    One retry, then raise. There is no third attempt and no partial-credit
    fallback: a request we could not parse twice is a request a human should see.
    """
    prompt = render_prompt(
        "extract_brief",
        raw_request=raw_request,
        campaign_types=CAMPAIGN_TYPES,
        audiences=AUDIENCES,
    )

    retried = False
    try:
        response = client.complete_json(prompt, schema_keys=EXTRACT_KEYS, model=CHEAP_MODEL)
    except LLMError:
        retried = True
        response = client.complete_json(prompt, schema_keys=EXTRACT_KEYS, model=CHEAP_MODEL)

    data = dict(response.data)
    data.pop("_confidence", None)
    data.pop("_note", None)

    # Reject values outside the allowed vocabularies rather than coercing them.
    # A campaign type we do not recognise becomes a missing field, which becomes
    # a question — not a silent guess at the nearest match.
    if data.get("campaign_type") not in CAMPAIGN_TYPES:
        data["campaign_type"] = None
    if data.get("audience") not in AUDIENCES:
        data["audience"] = None

    brief = Brief.from_dict(data)
    brief.raw_request = raw_request
    brief.requester = requester
    brief.source = source

    return ExtractionResult(
        brief=brief,
        confidence=float(response.confidence),
        retried=retried,
        raw=response.raw,
        model=response.model,
    )


@dataclass
class ClarificationResult:
    questions: list[str]
    missing: list[str]
    model: str


def clarify_gaps(brief: Brief, client: BaseClient) -> ClarificationResult:
    """
    `missing` is computed by the schema. The model only writes the wording.

    If the model is unavailable we still return usable questions from the
    static labels — the gap detection itself never depends on a model call.
    """
    missing = brief.missing_fields()
    if not missing:
        return ClarificationResult(questions=[], missing=[], model="none")

    known = {
        k: v for k, v in brief.to_dict().items()
        if v and k not in ("raw_request", "source")
    }

    prompt = render_prompt(
        "clarify_gaps",
        missing_fields=missing,
        known_fields="\n".join(f"{k}: {v}" for k, v in known.items()),
    )

    try:
        response = client.complete_json(prompt, schema_keys=["questions"], model=CHEAP_MODEL)
        questions = [str(q) for q in response.data["questions"]][:5]
        model = response.model
    except LLMError:
        questions = [
            f"Could you tell me {FIELD_LABELS.get(f, f.replace('_', ' '))}?"
            for f in missing[:5]
        ]
        model = "fallback:static"

    return ClarificationResult(questions=questions, missing=missing, model=model)


URL_FIELDS = ("cta_url", "resource_url", "image_url")


def normalise_answer(field_name: str, value: str) -> str | None:
    """
    Coerce a prose answer into the field's actual vocabulary.

    Requesters type "product launch", not "product_launch", and paste
    "figma.com/x" as often as a full URL. Storing the raw string would put an
    invalid value in a typed field, which then fails validation for a reason
    the requester can't act on ("'product launch' is not a known campaign
    type" is a useless thing to say to the person who just typed it).

    Returns None when the answer cannot be coerced — the field stays empty and
    gets asked again, which is the honest outcome.
    """
    value = value.strip().strip('."\'')
    if not value:
        return None

    if field_name in ("campaign_type", "audience"):
        slug = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
        allowed = CAMPAIGN_TYPES if field_name == "campaign_type" else AUDIENCES
        if slug in allowed:
            return slug
        # Tolerate near-misses: "launch" -> "product_launch", "devs" -> "developers"
        for option in allowed:
            if slug in option or option.startswith(slug) or slug in option.split("_"):
                return option
        return None

    if field_name in URL_FIELDS:
        if value.startswith("https://"):
            return value
        if value.startswith("http://"):
            return "https://" + value[7:]
        # A bare domain is a URL the requester meant; upgrading it is safe
        # because the shape is unambiguous. Free text is not, and returns None.
        if re.match(r"^[\w.-]+\.[a-z]{2,}(/\S*)?$", value, re.I):
            return "https://" + value
        return None

    return value


def apply_answers(brief: Brief, answers: dict[str, str]) -> Brief:
    """Merge replies back in. Only ever fills blanks; never overwrites."""
    data = brief.to_dict()
    for key, raw in answers.items():
        if key in data and (data[key] in (None, "", [])):
            coerced = normalise_answer(key, raw)
            if coerced is not None:
                data[key] = coerced
    merged = Brief.from_dict(data)
    merged.raw_request = brief.raw_request
    merged.requester = brief.requester
    merged.source = brief.source
    return merged


def match_answers(fields: list[str], lines: list[str]) -> dict[str, str]:
    """
    Map threaded replies to the fields we asked about.

    Naive positional zip breaks the moment someone answers a question we
    didn't ask, or skips one — everything after it shifts into the wrong
    field, and the failure is silent. So: claim the unambiguous answers by
    shape first (URLs to URL fields), then fill what's left positionally.
    """
    remaining_fields = list(fields)
    remaining_lines = list(lines)
    matched: dict[str, str] = {}

    # URLs are unmistakable. Claim them regardless of position.
    url_fields = [f for f in remaining_fields if f in URL_FIELDS]
    for field_name in url_fields:
        for line in list(remaining_lines):
            if re.search(r"(https?://|^[\w.-]+\.[a-z]{2,}(/|$))", line.strip(), re.I):
                matched[field_name] = line.strip()
                remaining_lines.remove(line)
                remaining_fields.remove(field_name)
                break

    # Controlled-vocabulary fields: claim a line that actually coerces.
    for field_name in [f for f in remaining_fields if f in ("campaign_type", "audience")]:
        for line in list(remaining_lines):
            if normalise_answer(field_name, line) is not None:
                matched[field_name] = line.strip()
                remaining_lines.remove(line)
                remaining_fields.remove(field_name)
                break

    # Whatever is left, in order.
    for field_name, line in zip(remaining_fields, remaining_lines):
        matched[field_name] = line.strip()

    return matched
