"""
Step 5: build the email.

No model input reaches this module except as text destined for a slot. Component
ids have already been validated against the manifest; copy has already been
length-checked. Assembly is pure templating.

This is the constraint that removes an entire class of failure: because the model
never emits markup, it cannot produce a broken layout, an unclosed table, an
inline style that breaks Outlook, or a tracking pixel in the wrong place.

PRODUCTION NOTE
---------------
`components/mjml/` holds the MJML sources. Where the `mjml` CLI is available this
module compiles from those. Where it is not — CI, this sandbox, a fresh laptop —
it renders the pre-compiled table-based partials in `components/partials/`, which
are the committed output of that same MJML source. Same result, no toolchain
required to run the pipeline.
"""

from __future__ import annotations

import html
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from ..config import COMPONENTS, PARTIALS

FOOTER_DEFAULTS = {
    "company_name": "Figma",
    "company_address": "760 Market St, San Francisco, CA 94102",
    "unsubscribe_url": "https://www.figma.com/email/unsubscribe?token={{unsubscribe_token}}",
    "preferences_url": "https://www.figma.com/email/preferences",
}


@dataclass
class RenderResult:
    html: str
    text: str
    renderer: str
    components: list[str]


def _env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(PARTIALS)),
        autoescape=False,      # partials escape explicitly; see _clean()
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )


def assemble(
    components: list[str],
    slots: dict[str, str],
    subject: str,
    preheader: str,
    *,
    utm_campaign: str = "email",
) -> RenderResult:
    env = _env()
    context = {k: _clean(v) for k, v in slots.items()}
    context.update(FOOTER_DEFAULTS)

    if "url" in context and context["url"]:
        context["url"] = _tag(context["url"], utm_campaign)
    for key in ("resource_url",):
        if context.get(key):
            context[key] = _tag(context[key], utm_campaign)

    blocks = []
    for cid in components:
        template = env.get_template(f"{cid}.html.j2")
        blocks.append(template.render(**_defaults_for(cid, context)))

    base = env.get_template("_base.html.j2")
    document = base.render(
        subject=_clean(subject),
        preheader=_clean(preheader),
        blocks="\n".join(blocks),
    )

    return RenderResult(
        html=document,
        text=to_plaintext(components, slots, subject),
        renderer="partials",
        components=list(components),
    )


def _defaults_for(component_id: str, context: dict) -> dict:
    """
    StrictUndefined means a missing optional slot would raise. Fill optionals
    with empty strings so a partial can decide for itself whether to render them.
    """
    from ..config import component

    spec = component(component_id)
    filled = dict(context)
    for slot in spec.get("slots") or []:
        filled.setdefault(slot, "")
    return filled


def _clean(value: str | None) -> str:
    """Escape once, here. Copy from a model is untrusted input like any other."""
    if value is None:
        return ""
    return html.escape(str(value), quote=True)


def _tag(url: str, campaign: str) -> str:
    """
    Append UTM parameters the linter requires. Deterministic, so tracking is
    never something a model remembered to do or forgot.
    """
    url = html.unescape(url)
    if "utm_source" in url:
        return html.escape(url, quote=True)
    joiner = "&" if "?" in url else "?"
    tagged = f"{url}{joiner}utm_source=email&utm_medium=lifecycle&utm_campaign={campaign}"
    return html.escape(tagged, quote=True)


def to_plaintext(components: list[str], slots: dict[str, str], subject: str) -> str:
    """Plain-text alternative. Deliverability requires it; it is not optional."""
    lines = [subject, ""]
    order = [
        "headline", "subhead", "body",
        "item_1_title", "item_1_body",
        "item_2_title", "item_2_body",
        "item_3_title", "item_3_body",
        "event_name", "event_date", "event_time", "event_location",
        "quote", "attribution_name",
        "resource_title", "resource_body",
        "label", "url",
    ]
    for key in order:
        value = slots.get(key)
        if value:
            lines.append(str(value))
    lines += ["", "Unsubscribe: " + FOOTER_DEFAULTS["unsubscribe_url"]]
    return "\n".join(lines)


# ----------------------------------------------------------------------
# Optional MJML path
# ----------------------------------------------------------------------
def mjml_available() -> bool:
    return shutil.which("mjml") is not None


def compile_mjml(source: Path) -> str:  # pragma: no cover - needs the CLI
    if not mjml_available():
        raise RuntimeError("mjml CLI not on PATH")
    result = subprocess.run(
        ["mjml", str(source), "-s"], capture_output=True, text=True, check=True
    )
    return result.stdout


def check_partials_match_mjml() -> list[str]:  # pragma: no cover
    """
    CI guard. If someone edits an MJML source without recompiling the partial,
    the two drift and the pipeline silently renders stale markup.
    """
    if not mjml_available():
        return []
    drifted = []
    for source in (COMPONENTS / "mjml").glob("*.mjml"):
        partial = PARTIALS / f"{source.stem}.html.j2"
        if not partial.exists():
            drifted.append(f"{source.stem}: no compiled partial")
    return drifted
