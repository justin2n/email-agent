"""
Step 6a: the deterministic brand check.

Every rule here is decided with certainty from `brand/rules.yaml`. No model, no
threshold, no ambiguity. These run in milliseconds, cost nothing, and are right
100% of the time — which is exactly why they should never be delegated to a model.

Severity:
  BLOCK  - cannot proceed under any circumstances
  FLAG   - proceeds, but a human is told
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from ..config import brand_rules

Severity = Literal["block", "flag"]


@dataclass
class Finding:
    rule: str
    severity: Severity
    message: str
    evidence: str = ""

    def __str__(self) -> str:
        base = f"[{self.severity.upper()}] {self.rule}: {self.message}"
        return f"{base} — {self.evidence!r}" if self.evidence else base


@dataclass
class LintResult:
    findings: list[Finding]

    @property
    def blocks(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "block"]

    @property
    def flags(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "flag"]

    @property
    def passed(self) -> bool:
        return not self.blocks

    def summary(self) -> str:
        if not self.findings:
            return "clean"
        return f"{len(self.blocks)} blocking, {len(self.flags)} flagged"


TAG_RE = re.compile(r"<[^>]+>")
LINK_RE = re.compile(r'href="([^"]+)"')
IMG_RE = re.compile(r"<img\b[^>]*>", re.I)
ALT_RE = re.compile(r'alt="([^"]*)"', re.I)


def lint(html: str, subject: str, preheader: str) -> LintResult:
    rules = brand_rules()
    findings: list[Finding] = []
    text = _visible_text(html)

    findings += _check_subject(subject, rules)
    findings += _check_preheader(preheader, subject, rules)
    findings += _check_links(html, rules)
    findings += _check_images(html, rules)
    findings += _check_ctas(html, rules)
    findings += _check_structure(html, text, rules)
    findings += _check_terms(f"{subject} {preheader} {text}", rules)

    return LintResult(findings=findings)


def _check_subject(subject: str, rules: dict) -> list[Finding]:
    cfg = rules["subject_line"]
    out: list[Finding] = []
    if not subject.strip():
        return [Finding("subject.missing", "block", "no subject line")]
    n = len(subject)
    if n < cfg["min_chars"]:
        out.append(Finding("subject.too_short", "block",
                           f"{n} chars, minimum is {cfg['min_chars']}", subject))
    if n > cfg["max_chars"]:
        out.append(Finding("subject.too_long", "block",
                           f"{n} chars, maximum is {cfg['max_chars']}", subject))
    if cfg.get("forbid_all_caps") and subject.isupper():
        out.append(Finding("subject.all_caps", "block", "subject is all caps", subject))
    if subject.count("!") > cfg.get("max_exclamations", 0):
        out.append(Finding("subject.exclamation", "block",
                           "house style allows no exclamation marks", subject))
    if cfg.get("forbid_leading_emoji") and subject and ord(subject[0]) > 0x2100:
        out.append(Finding("subject.leading_emoji", "flag",
                           "subject opens with an emoji", subject[:12]))
    return out


def _check_preheader(preheader: str, subject: str, rules: dict) -> list[Finding]:
    cfg = rules["preheader"]
    out: list[Finding] = []
    if cfg.get("required") and not preheader.strip():
        return [Finding("preheader.missing", "block", "no preheader set")]
    n = len(preheader)
    if n < cfg["min_chars"]:
        out.append(Finding("preheader.too_short", "flag",
                           f"{n} chars, minimum is {cfg['min_chars']}", preheader))
    if n > cfg["max_chars"]:
        out.append(Finding("preheader.too_long", "flag",
                           f"{n} chars, maximum is {cfg['max_chars']}", preheader))
    if cfg.get("forbid_duplicate_of_subject") and preheader.strip() == subject.strip():
        out.append(Finding("preheader.duplicate", "flag",
                           "preheader repeats the subject line", preheader))
    return out


def _check_links(html: str, rules: dict) -> list[Finding]:
    cfg = rules["links"]
    out: list[Finding] = []
    for raw in LINK_RE.findall(html):
        url = raw.replace("&amp;", "&")
        if "{{" in url:            # unsubscribe token is templated by the ESP
            continue
        # Footer links are system chrome, not campaign links. Requiring UTM
        # parameters on an unsubscribe link would be a false positive that
        # teaches reviewers to ignore the linter.
        if any(seg in url for seg in ("/email/unsubscribe", "/email/preferences")):
            continue
        if cfg.get("require_https") and not url.startswith("https://"):
            out.append(Finding("links.not_https", "block", "link is not https", url))
            continue
        missing = [p for p in cfg.get("require_utm", []) if p not in url]
        if missing:
            out.append(Finding("links.missing_utm", "block",
                               f"missing tracking parameters: {', '.join(missing)}", url))
        if cfg.get("forbid_bare_domains") and re.fullmatch(r"https://[\w.-]+/?", url):
            out.append(Finding("links.bare_domain", "flag",
                               "links to a bare domain with no path", url))
    return out


def _check_images(html: str, rules: dict) -> list[Finding]:
    cfg = rules["images"]
    out: list[Finding] = []
    images = IMG_RE.findall(html)
    if len(images) > cfg.get("max_count", 99):
        out.append(Finding("images.too_many", "flag",
                           f"{len(images)} images, maximum is {cfg['max_count']}"))
    for tag in images:
        alt = ALT_RE.search(tag)
        if cfg.get("require_alt_text") and (not alt or not alt.group(1).strip()):
            out.append(Finding("images.no_alt", "block",
                               "image has no alt text", tag[:70]))
        elif alt and len(alt.group(1)) < cfg.get("min_alt_chars", 0):
            out.append(Finding("images.alt_too_short", "flag",
                               "alt text is too short to be useful", alt.group(1)))
    return out


def _check_ctas(html: str, rules: dict) -> list[Finding]:
    cfg = rules["calls_to_action"]
    out: list[Finding] = []
    anchors = re.findall(r"<a\b[^>]*>(.*?)</a>", html, re.S | re.I)
    labels = [TAG_RE.sub("", a).strip() for a in anchors]
    # Footer links are structural, not calls to action.
    labels = [l for l in labels if l.lower() not in
              ("unsubscribe", "email preferences", "preferences")]

    if len(labels) < cfg["min_count"]:
        out.append(Finding("cta.too_few", "block",
                           f"{len(labels)} calls to action, minimum is {cfg['min_count']}"))
    if len(labels) > cfg["max_count"]:
        out.append(Finding("cta.too_many", "block",
                           f"{len(labels)} calls to action, maximum is {cfg['max_count']}",
                           " | ".join(labels)))

    forbidden = {f.lower() for f in cfg.get("forbid_labels", [])}
    for label in labels:
        clean = label.replace("\u2192", "").replace("&rarr;", "").strip()
        if clean.lower() in forbidden:
            out.append(Finding("cta.weak_label", "block",
                               "label is on the forbidden list", clean))
        elif len(clean) < cfg["min_label_chars"]:
            out.append(Finding("cta.label_too_short", "flag",
                               f"'{clean}' is under {cfg['min_label_chars']} chars", clean))
        elif len(clean) > cfg["max_label_chars"]:
            out.append(Finding("cta.label_too_long", "flag",
                               f"'{clean}' is over {cfg['max_label_chars']} chars", clean))
    return out


def _check_structure(html: str, text: str, rules: dict) -> list[Finding]:
    cfg = rules["structure"]
    out: list[Finding] = []
    if cfg.get("require_unsubscribe") and "unsubscribe" not in html.lower():
        out.append(Finding("structure.no_unsubscribe", "block",
                           "no unsubscribe link — this is a legal requirement"))
    words = len(text.split())
    if words > cfg.get("max_word_count", 10**6):
        out.append(Finding("structure.too_long", "flag",
                           f"{words} words, house maximum is {cfg['max_word_count']}"))
    if words < cfg.get("min_word_count", 0):
        out.append(Finding("structure.too_short", "flag",
                           f"only {words} words — likely an under-filled brief"))
    return out


def _check_terms(text: str, rules: dict) -> list[Finding]:
    out: list[Finding] = []
    low = text.lower()

    for pattern in rules.get("placeholder_patterns", []):
        if pattern.lower() in low:
            out.append(Finding("content.placeholder", "block",
                               "unresolved placeholder text in the email", pattern))

    for term in rules.get("banned_terms", []):
        if re.search(rf"\b{re.escape(term.lower())}\b", low):
            out.append(Finding("content.banned_term", "block",
                               f"'{term}' is on the banned list", term))

    for term in rules.get("review_required_terms", []):
        if re.search(rf"(?<!\w){re.escape(term.lower())}(?!\w)", low):
            out.append(Finding("content.needs_legal_review", "flag",
                               f"'{term}' is a claim that needs legal sign-off", term))
    return out


def _visible_text(html: str) -> str:
    body = re.sub(r"<(script|style)\b.*?</\1>", " ", html, flags=re.S | re.I)
    # Drop the hidden preheader div so it is not double-counted as body copy.
    body = re.sub(r'<div style="display:none.*?</div>', " ", body, flags=re.S | re.I)
    text = TAG_RE.sub(" ", body)
    text = (text.replace("&nbsp;", " ").replace("&middot;", " ")
                .replace("&ldquo;", '"').replace("&rdquo;", '"')
                .replace("&rarr;", " ").replace("&amp;", "&"))
    return re.sub(r"\s+", " ", text).strip()
