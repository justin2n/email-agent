"""
The anti-hallucination check.

Everything factual in the finished email is compared against what the requester
actually supplied. A number, date, price, percentage or proper noun that appears
in the output but has no basis in the brief is treated as invented.

This is deliberately a *code* check, not a prompt instruction. "Please don't make
things up" is a request. This is a verification.

It is intentionally tuned to over-flag rather than under-flag. A false positive
costs a human ten seconds; a false negative puts an invented product claim in a
customer's inbox.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..models.brief import Brief
from .lint import _visible_text

# Numbers, money, percentages, dates.
NUMERIC_RE = re.compile(
    r"(?<![\w/])(?:"
    r"\$\s?\d[\d,]*(?:\.\d+)?"
    r"|\d+(?:\.\d+)?\s?%"
    r"|\d{4}-\d{2}-\d{2}"
    r"|\b\d[\d,]{2,}\b"
    r"|\b\d+(?:\.\d+)?x\b"
    r")"
)

# Capitalised multi-word phrases — product names, company names, people.
PROPER_RE = re.compile(r"\b[A-Z][a-zA-Z0-9]+(?:\s+[A-Z][a-zA-Z0-9]+){0,3}\b")

# Words that get capitalised by position, not because they're proper nouns.
COMMON = {
    "the", "a", "an", "we", "you", "your", "our", "it", "this", "that", "here",
    "what", "why", "how", "when", "where", "who", "and", "or", "but", "for",
    "with", "from", "see", "get", "join", "read", "learn", "start", "try",
    "unsubscribe", "email", "preferences", "figma", "monday", "tuesday",
    "wednesday", "thursday", "friday", "saturday", "sunday", "january",
    "february", "march", "april", "may", "june", "july", "august", "september",
    "october", "november", "december", "new", "now", "more", "all", "in", "on",
    "to", "of", "is", "are", "be", "by", "at", "as", "if", "so", "up", "out",
}


@dataclass
class GroundingResult:
    invented_numbers: list[str] = field(default_factory=list)
    invented_entities: list[str] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return not self.invented_numbers and not self.invented_entities

    def summary(self) -> str:
        if self.clean:
            return "grounded"
        bits = []
        if self.invented_numbers:
            bits.append(f"{len(self.invented_numbers)} unsupported figure(s)")
        if self.invented_entities:
            bits.append(f"{len(self.invented_entities)} unsupported name(s)")
        return ", ".join(bits)


def check_grounding(html: str, subject: str, preheader: str, brief: Brief) -> GroundingResult:
    # The footer is boilerplate the system inserts, not content the model wrote.
    # Grounding it against the brief would flag our own office address as an
    # invented fact on every single email.
    body_html = _strip_footer(html)
    output_text = f"{subject} {preheader} {_visible_text(body_html)}"
    source = brief.grounding_corpus()
    source_norm = _normalise(source)

    invented_numbers = []
    for match in NUMERIC_RE.findall(output_text):
        if _normalise(match) not in source_norm:
            invented_numbers.append(match)

    invented_entities = []
    for match in PROPER_RE.findall(output_text):
        if len(match) < 4:
            continue
        words = match.split()
        if all(w.lower() in COMMON for w in words):
            continue
        # Single capitalised words at sentence starts are too noisy to judge.
        if len(words) == 1 and match.lower() in COMMON:
            continue
        # Match on words, not the exact phrase. "Android Copy CSS" is a phrase
        # the renderer assembled from adjacent brief content; every word in it
        # came from the requester, so it is not invented. Only flag a phrase
        # containing a word that appears nowhere in the brief.
        novel = [w for w in words
                 if w.lower() not in COMMON and _normalise(w) not in source_norm]
        if novel:
            invented_entities.append(match)

    return GroundingResult(
        invented_numbers=_dedupe(invented_numbers),
        invented_entities=_dedupe(invented_entities),
    )


FOOTER_RE = re.compile(
    r'<tr><td style="padding:24px 40px 32px 40px;border-top.*?</tr>', re.S)


def _strip_footer(html: str) -> str:
    return FOOTER_RE.sub(" ", html)


def _normalise(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _dedupe(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))
