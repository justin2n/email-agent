"""
Offline model responses.

These are intentionally *rule-based rather than random*: the stub reads the
actual prompt and produces a plausible structured answer from it. That means
the offline pipeline exercises real branching — a prompt with no offer in it
produces a response with no offer, and the grounding check downstream still
has something meaningful to catch.

It is not pretending to be a language model. It is a fixture generator good
enough to prove the surrounding system works.
"""

from __future__ import annotations

import re
from typing import Any


def respond(step: str, prompt: str, fixtures: dict[str, Any]) -> dict[str, Any]:
    if step in fixtures:
        return fixtures[step]
    handler = _HANDLERS.get(step)
    if handler is None:
        return {"_confidence": 0.0, "_note": f"no stub handler for step '{step}'"}
    return handler(prompt)


# ----------------------------------------------------------------------
# extract_brief
# ----------------------------------------------------------------------
_CAMPAIGN_HINTS = [
    ("webinar_reminder", ("reminder", "starting soon", "tomorrow at")),
    ("webinar_invite", ("webinar", "register", "livestream", "session")),
    ("product_launch", ("launch", "launching", "now available", "ga ", "general availability")),
    ("feature_announcement", ("new feature", "shipped", "rolling out", "update to")),
    ("customer_story", ("case study", "customer story", "testimonial", "quote from")),
    ("nurture_education", ("guide", "ebook", "e-book", "whitepaper", "tutorial", "nurture")),
    ("event_followup", ("thanks for attending", "follow up", "follow-up", "recap")),
    ("newsletter", ("newsletter", "monthly round", "roundup")),
]

_AUDIENCE_HINTS = [
    ("developers", ("developer", "engineer", "dev ", "api")),
    ("design_leaders", ("design lead", "head of design", "vp of design", "leader")),
    ("educators", ("teacher", "educator", "professor", "faculty")),
    ("students", ("student", "university", "campus")),
    ("enterprise_it", ("enterprise", "it admin", "security", "sso", "admin")),
    ("trial_users", ("trial", "free tier", "starter")),
    ("churned_users", ("churn", "lapsed", "win-back", "winback")),
    ("designers", ("designer", "design team", "product design")),
]


MENTION_RE = re.compile(
    r"^\s*(?:<@[A-Z0-9]+>|@[\w.\-]+(?:\s+[A-Z][\w.\-]*)*)[\s,:\-]*")


def _extract_brief(prompt: str) -> dict[str, Any]:
    request = _section(prompt, "request")
    # Strip a leading @mention / Slack user ref before anything reads the text.
    request = MENTION_RE.sub("", request, count=1)
    low = request.lower()

    out: dict[str, Any] = {
        "campaign_type": _first_hint(low, _CAMPAIGN_HINTS),
        "audience": _first_hint(low, _AUDIENCE_HINTS),
        "primary_message": _primary_message(request),
        "cta_label": None,
        "cta_url": None,
        "send_window": None,
        "supporting_points": [],
        "_confidence": 0.82,
    }

    url = re.search(r"https://[^\s,;)\"']+", request)
    if url:
        out["cta_url"] = url.group(0).rstrip(".")

    # Two phrasings cover most real requests: 'button should say "X"' and 'Button: "X"'.
    cta = re.search(
        r"(?:button|cta|link)\s*(?:should\s*)?(?:say|reads?|labell?ed)?\s*:?\s*"
        r"[\"'\u201c]([^\"'\u201d\n]{3,40})[\"'\u201d]",
        request, re.I,
    )
    if cta:
        out["cta_label"] = cta.group(1).strip()

    DAY = r"(?:mon|tues|wednes|thurs|fri|satur|sun)day"
    when = re.search(
        r"(?:send|sending|ship|shipping|go|goes|going|live|launch)\s*"
        r"(?:it\s*|out\s*|to\s*)*(?:on|by|before)?\s*"
        rf"((?:next|this)\s+(?:week|month|{DAY})|"
        rf"end of (?:the\s+)?\w+|{DAY}|\d{{1,2}}\s+\w+|\w+\s+\d{{1,2}})",
        request, re.I,
    )
    if when:
        out["send_window"] = when.group(1).strip()

    # 'Event: Name, 2026-11-18, 11am PT, 45 minutes, online'
    ev_line = re.search(r"^\s*event\s*:\s*(.+)$", request, re.I | re.M)
    if ev_line:
        parts = [p.strip() for p in ev_line.group(1).split(",")]
        if parts:
            out["event_name"] = parts[0].rstrip(".")
        for part in parts[1:]:
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", part):
                out["event_date"] = part
            elif re.search(r"\d\s*(?:am|pm)", part, re.I):
                out["event_time"] = part
            elif re.search(r"\bminutes?\b|\bhours?\b", part, re.I):
                out["event_duration"] = part
            else:
                out.setdefault("event_location", part.rstrip("."))

    ev = re.search(r"(?:on|scheduled for)\s+((?:\d{4}-\d{2}-\d{2})|(?:\w+ \d{1,2},? \d{4}))", request, re.I)
    if ev and not out.get("event_date"):
        out["event_date"] = ev.group(1).strip()
    et = re.search(r"(\d{1,2}(?::\d{2})?\s*(?:am|pm)\s*(?:[A-Z]{2,4})?)", request, re.I)
    if et:
        out["event_time"] = et.group(1).strip()

    # 'Resource: The Design Systems Handbook, https://...'
    res_line = re.search(r"^\s*resource\s*:\s*(.+)$", request, re.I | re.M)
    if res_line:
        parts = [p.strip() for p in res_line.group(1).split(",")]
        for part in parts:
            if part.startswith("http"):
                out["resource_url"] = part.rstrip(".")
            elif not out.get("resource_title"):
                out["resource_title"] = part.rstrip(".")

    quoted = re.findall(r"[\"“]([^\"”]{25,220})[\"”]", request)
    if quoted and out["campaign_type"] == "customer_story":
        out["quote"] = quoted[0]

    points = re.findall(r"^\s*[-*\u2022]\s*(.+)$", request, re.M)
    if points:
        out["supporting_points"] = [p.strip() for p in points[:4]]

    return out


VAGUE = (
    "can we get", "can you get", "can we do", "can you do", "could we get",
    "something out about", "the new thing", "an email about", "email for the",
    "need an email", "we need something", "anything for", "get something out",
)


def _primary_message(request: str) -> str | None:
    """
    The one thing the email should say - or None.

    A vague ask names a topic, not a message. Returning it anyway would mark
    primary_message as filled and skip the single most important question,
    which is exactly how an agent ends up writing a confident email about
    nothing in particular.
    """
    for line in (l.strip() for l in request.splitlines()):
        if len(line) <= 25 or line.startswith(("-", "*", "•", ">")):
            continue
        low = line.lower()
        # "Requested change: lead on the free tier" is an instruction about the
        # email, not a fact to put in it. Treating it as the message produced
        # subject lines like "Requested change: Lead is here".
        if low.startswith(("requested change:", "change:", "note:", "fyi:")):
            continue
        if any(marker in low for marker in VAGUE) or line.endswith("?"):
            continue
        return line.rstrip(".")[:200]
    return None


# ----------------------------------------------------------------------
# clarify_gaps
# ----------------------------------------------------------------------
def _clarify_gaps(prompt: str) -> dict[str, Any]:
    fields = [f.strip() for f in _section(prompt, "missing_fields").split(",") if f.strip()]
    questions = {
        "campaign_type": "What kind of email is this — a launch, a webinar invite, a nurture send, something else?",
        "audience": "Who's receiving this? (designers, developers, design leaders, enterprise IT, trial users…)",
        "primary_message": "What's the single main thing you want this email to say?",
        "cta_label": "What should the button say? Something specific beats \u201cLearn more\u201d.",
        "cta_url": "Where should the button go? Full https link, please.",
        "send_window": "When does this need to go out?",
        "event_name": "What's the event called?",
        "event_date": "What date is the event?",
        "event_time": "What time, and in which time zone?",
        "quote": "Can you paste the approved customer quote?",
        "quote_attribution_name": "Who is the quote from?",
        "resource_title": "What's the resource called?",
        "resource_url": "What's the link to the resource?",
    }
    asked = [questions.get(f, f"Could you tell me the {f.replace('_', ' ')}?") for f in fields]
    return {"questions": asked, "_confidence": 0.95}


# ----------------------------------------------------------------------
# select_components
# ----------------------------------------------------------------------
def _select_components(prompt: str) -> dict[str, Any]:
    allowed = [c.strip() for c in _section(prompt, "allowed_components").split(",") if c.strip()]
    picked = [c for c in ("hero_headline", "body_text", "cta_button", "footer_standard") if c in allowed]
    return {
        "components": picked or allowed[:3],
        "reasoning": "No deterministic sequence matched this campaign type; "
                     "fell back to the default opener/body/action/footer shape.",
        "_confidence": 0.6,
    }


# ----------------------------------------------------------------------
# generate_copy
# ----------------------------------------------------------------------
def _generate_copy(prompt: str) -> dict[str, Any]:
    """
    Offline copy generation.

    Echoing the brief back produces subject lines like "We are launching Dev
    Mode Inspect for developers next" - technically grounded, obviously
    machine-made. This composes readable copy from the brief's own vocabulary
    instead: it extracts the subject, the capability and the benefit, then
    writes sentences around them.

    Still not a language model. But it produces something a marketer would
    recognise as an email, which is what an offline demo needs.
    """
    msg = _section(prompt, "primary_message") or "There's an update to share."
    audience = _section(prompt, "audience") or "all_users"
    points = [p.strip("-\u2022 ") for p in _section(prompt, "supporting_points").splitlines() if p.strip()]
    cta_label = _section(prompt, "cta_label") or "See what's new"
    event_name = _section(prompt, "event_name")
    resource_title = _section(prompt, "resource_title")
    quote = _section(prompt, "quote")
    wanted = [x.strip() for x in _section(prompt, "slots").split(",") if x.strip()]

    subject_noun = _subject_noun(msg, event_name, resource_title)
    benefit = _benefit_clause(msg)
    who = _audience_phrase(audience)

    # Headline: the noun plus what it does, not the whole sentence.
    if event_name:
        headline = _trim(event_name, 56)
    elif resource_title:
        headline = _trim(resource_title, 56)
    elif benefit:
        headline = _trim(_sentence_case(f"{subject_noun}: {benefit}"), 56)
    else:
        headline = _trim(_sentence_case(subject_noun), 56)

    # points[0] becomes item_1_title/body, so leading with it duplicates copy.
    if benefit:
        subhead = _trim(_sentence_case(benefit), 116)
    elif len(points) > 2:
        subhead = _trim(_sentence_case(points[-1]), 116)
    else:
        subhead = _trim(_sentence_case(_strip_timing(msg)), 116)

    body = _sentence_case(_strip_timing(msg).rstrip("."))
    body += f". For {who}, that means fewer handoffs and less waiting."
    if len(points) > 1:
        body += f" {_sentence_case(points[1].rstrip('.'))}."

    filled: dict[str, str] = {}
    for slot in wanted:
        if slot == "headline":
            filled[slot] = headline
        elif slot == "subhead":
            filled[slot] = subhead
        elif slot == "body":
            filled[slot] = _trim(body, 390)
        elif slot == "label":
            filled[slot] = _trim(cta_label, 30)
        elif slot == "url":
            filled[slot] = _section(prompt, "cta_url") or "https://www.figma.com"
        elif slot == "resource_label":
            filled[slot] = _trim(cta_label or "Read the guide", 30)
        elif slot == "resource_body":
            filled[slot] = _trim(_sentence_case(msg), 155)
        elif slot == "quote":
            filled[slot] = _trim(quote, 218) if quote else ""
        elif slot.startswith("item_") and slot.endswith("_title"):
            idx = int(slot.split("_")[1]) - 1
            filled[slot] = _trim(_title_from(points[idx]), 30) if idx < len(points) else ""
        elif slot.startswith("item_") and slot.endswith("_body"):
            idx = int(slot.split("_")[1]) - 1
            filled[slot] = _trim(_sentence_case(points[idx]), 105) if idx < len(points) else ""
        else:
            src = _section(prompt, slot)
            if src:
                filled[slot] = src

    # Three genuinely different subject lines, so the choice is real.
    candidates = [
        _trim(_sentence_case(f"You're invited: {event_name}"), 55) if event_name
        else _trim(_sentence_case(f"{subject_noun} is here"), 55),
        headline,
        _trim(_sentence_case(points[0]), 55) if points
        else _trim(_sentence_case(benefit or subject_noun), 55),
    ]
    # A 16-character subject technically passes the rule and still reads thin.
    # Order by how well each fills the line, so the pick is the fullest that fits.
    unique = list(dict.fromkeys(c for c in candidates if c))
    options = [o for o in unique if 20 <= len(o) <= 60]
    if not options:
        options = [o for o in unique if 15 <= len(o) <= 60]
    if not options:
        options = [_trim(_sentence_case(msg), 55)]

    # Must differ from both the subject and the subhead - it is the third
    # line of copy the reader sees, not a repeat of the first two.
    if points:
        preheader = _sentence_case(points[0].rstrip(".")) + ", and more."
    else:
        preheader = _sentence_case(_strip_timing(msg).rstrip(".")) + "."
    if len(preheader) < 45:
        preheader += f" Here's what it means for {who}."
    preheader = _trim(preheader, 96)

    return {
        "slots": filled,
        "subject_options": options,
        "preheader": preheader,
        "_confidence": 0.78,
    }


# Verbs that introduce the thing rather than name it.
_LEAD_VERBS = re.compile(
    r"^(?:we(?:'re| are)?\s+)?(?:now\s+)?(?:launching|releasing|shipping|"
    r"announcing|introducing|rolling out|bringing)\s+", re.I)


def _subject_noun(msg: str, event_name: str, resource_title: str) -> str:
    """The thing the email is about, without the announcement scaffolding."""
    if event_name:
        return event_name
    if resource_title:
        return resource_title
    text = _LEAD_VERBS.sub("", msg.strip().rstrip("."))
    # Cut at the first clause boundary - "X for developers next Tuesday" -> "X"
    for marker in (" for ", " to ", " so ", " which ", " that ", " on ", " next "):
        idx = text.lower().find(marker)
        if 3 < idx < 60:
            text = text[:idx]
            break
    return text.strip() or msg[:50]


_TIMING = re.compile(
    r"\s+(?:next|this|on|by)\s+(?:week|month|monday|tuesday|wednesday|thursday|"
    r"friday|saturday|sunday)\b", re.I)


def _strip_timing(msg: str) -> str:
    """Send timing belongs in the schedule, not in the body copy."""
    return _TIMING.sub("", msg).strip()


def _benefit_clause(msg: str) -> str:
    """The 'so that' half of the message, if the requester gave one."""
    for marker in (" so you can ", " so that ", " which means ", " without "):
        idx = msg.lower().find(marker)
        if idx > 0:
            tail = msg[idx:].strip().rstrip(".")
            if marker == " without ":
                tail = "no " + msg[idx + len(marker):].strip().rstrip(".")
            return tail.strip()[:70]
    return ""


_STOP_AT = re.compile(r"[,;:]| (?:from|for|in|on|with|between|across|to|of|at) ", re.I)


def _title_from(point: str) -> str:
    """
    A short label from a bullet.

    Truncating at a word count gives "Copy CSS, iOS and" - which reads as a
    bug. Cutting at the first clause boundary gives "Copy CSS" instead.
    """
    text = _sentence_case(point.rstrip("."))
    match = _STOP_AT.search(text)
    # Only cut if what's left still says something. "Works" is not a feature
    # title; "Works in the free tier" is.
    if match and match.start() >= 10:
        text = text[: match.start()]
    elif match:
        second = _STOP_AT.search(text, match.end())
        if second and second.start() <= 28:
            text = text[: second.start()]
    return _trim(text, 28)


def _audience_phrase(audience: str) -> str:
    return {
        "designers": "your design work",
        "developers": "your build process",
        "design_leaders": "your team",
        "educators": "your classroom",
        "students": "your projects",
        "enterprise_it": "your organisation",
        "trial_users": "your trial",
        "churned_users": "your team",
    }.get(audience, "your team")


def _trim(text: str, limit: int) -> str:
    """Word-boundary trim. Mid-word cuts read as a bug to the reader."""
    text = text.strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    if " " in cut:
        cut = cut[: cut.rfind(" ")]
    return cut.rstrip(" ,;:-")


def _sentence_case(text: str) -> str:
    text = text.strip().rstrip(".")
    return text[:1].upper() + text[1:] if text else text


# ----------------------------------------------------------------------
# vet_voice
# ----------------------------------------------------------------------
def _vet_voice(prompt: str) -> dict[str, Any]:
    copy = _section(prompt, "email_copy").lower()
    scores = {"plainness": 5, "directness": 4, "specificity": 4, "register_fit": 4, "restraint": 5}
    citations: dict[str, str] = {}

    hype = ("revolutionary", "game-chang", "seamless", "effortless", "supercharge", "world-class")
    for h in hype:
        if h in copy:
            scores["plainness"] = 2
            citations["plainness"] = f"uses hype language: '{h}'"
            break
    if "!" in copy:
        scores["restraint"] = 2
        citations["restraint"] = "contains an exclamation mark"
    if "we are excited to" in copy or "we're excited to" in copy:
        scores["directness"] = 3
        citations["directness"] = "opens with corporate hedging"
    if len(copy) < 120:
        scores["specificity"] = 3
        citations["specificity"] = "copy is very short; claims are thin"

    mean = sum(scores.values()) / len(scores)
    return {
        "scores": scores,
        "citations": citations,
        "mean": round(mean, 2),
        "_confidence": 0.85,
    }


_HANDLERS = {
    "extract_brief": _extract_brief,
    "clarify_gaps": _clarify_gaps,
    "select_components": _select_components,
    "generate_copy": _generate_copy,
    "vet_voice": _vet_voice,
}


def _section(prompt: str, tag: str) -> str:
    m = re.search(rf"<{tag}>(.*?)</{tag}>", prompt, re.S)
    return m.group(1).strip() if m else ""


def _first_hint(low: str, hints: list[tuple[str, tuple[str, ...]]]) -> str | None:
    for value, needles in hints:
        if any(n in low for n in needles):
            return value
    return None
