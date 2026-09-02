"""
The escalation router.

DELIBERATELY DETERMINISTIC. The model contributes evidence — a tone score, a
confidence value — but the decision to involve a human is made here, in code,
from thresholds that live in version control.

A model that decides when to ask for help can also decide not to. This module
exists so that never happens.

Every escalation carries the specific rule that fired and the evidence for it.
An escalation that says "something looked wrong" wastes the reviewer's time and
teaches them to ignore the next one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Route(str, Enum):
    PROCEED = "proceed"                    # straight to email team QA
    REQUESTER = "back_to_requester"        # brief is incomplete
    REVIEW = "flag_for_review"             # proceeds, human is warned
    BLOCK = "block"                        # stops here


# Priority order. The most severe route wins.
SEVERITY = {Route.PROCEED: 0, Route.REVIEW: 1, Route.REQUESTER: 2, Route.BLOCK: 3}


@dataclass
class Reason:
    rule: str
    route: Route
    message: str
    evidence: str = ""


@dataclass
class Decision:
    route: Route
    reasons: list[Reason] = field(default_factory=list)

    @property
    def stops(self) -> bool:
        return self.route in (Route.BLOCK, Route.REQUESTER)

    def explain(self) -> str:
        if not self.reasons:
            return "No issues found."
        return "\n".join(
            f"  - [{r.route.value}] {r.rule}: {r.message}"
            + (f"\n      evidence: {r.evidence}" if r.evidence else "")
            for r in self.reasons
        )


# Thresholds. Version-controlled, changed by PR, covered by evals.
THRESHOLDS = {
    "extraction_confidence": 0.70,
    "generation_confidence": 0.60,
    "selection_confidence": 0.55,
    "voice_mean": 4.0,
    "voice_min_dimension": 3,
    "max_clarify_rounds": 2,
    "max_preview_iterations": 4,
}


def decide(
    *,
    missing_fields: list[str] | None = None,
    validation_issues: list | None = None,
    extraction_confidence: float = 1.0,
    selection_path: str = "rule",
    selection_confidence: float = 1.0,
    unfillable_components: list[str] | None = None,
    generation_confidence: float = 1.0,
    empty_slots: list[str] | None = None,
    unknown_slots: list[str] | None = None,
    truncated_slots: list[str] | None = None,
    lint_result=None,
    grounding_result=None,
    voice_result=None,
    clarify_rounds: int = 0,
    preview_iterations: int = 0,
) -> Decision:
    """
    Single place where every signal in the pipeline is turned into a decision.

    Adding a new check means adding a branch here, not scattering `if bad: stop`
    through the steps — which is what keeps the escalation behaviour testable.
    """
    reasons: list[Reason] = []

    # ---- brief completeness -------------------------------------------------
    if missing_fields:
        reasons.append(Reason(
            "brief.incomplete", Route.REQUESTER,
            f"{len(missing_fields)} required field(s) missing",
            ", ".join(missing_fields),
        ))

    for issue in (validation_issues or []):
        route = Route.REQUESTER if issue.code in (
            "date_in_past", "bad_url", "missing_attribution") else Route.REVIEW
        reasons.append(Reason(f"brief.{issue.code}", route, issue.message, issue.field))

    if clarify_rounds >= THRESHOLDS["max_clarify_rounds"]:
        reasons.append(Reason(
            "brief.clarify_exhausted", Route.REVIEW,
            f"still incomplete after {clarify_rounds} rounds — a person should take this over",
        ))

    # ---- model confidence ---------------------------------------------------
    if extraction_confidence < THRESHOLDS["extraction_confidence"]:
        reasons.append(Reason(
            "extraction.low_confidence", Route.REQUESTER,
            f"confidence {extraction_confidence:.2f} below "
            f"{THRESHOLDS['extraction_confidence']:.2f} — the request was too ambiguous to read",
        ))

    if selection_path == "model":
        reasons.append(Reason(
            "selection.model_fallback", Route.REVIEW,
            "no deterministic sequence matched; components were chosen by the model",
        ))
        if selection_confidence < THRESHOLDS["selection_confidence"]:
            reasons.append(Reason(
                "selection.low_confidence", Route.BLOCK,
                f"fallback selection confidence {selection_confidence:.2f} is too low to build on",
            ))

    if generation_confidence < THRESHOLDS["generation_confidence"]:
        reasons.append(Reason(
            "generation.low_confidence", Route.REVIEW,
            f"copy generation confidence {generation_confidence:.2f} is low",
        ))

    # ---- content completeness ----------------------------------------------
    if unfillable_components:
        reasons.append(Reason(
            "selection.unfillable", Route.REQUESTER,
            "selected components need content the brief does not contain",
            "; ".join(unfillable_components),
        ))

    if empty_slots:
        reasons.append(Reason(
            "generation.empty_slots", Route.REQUESTER,
            f"{len(empty_slots)} slot(s) could not be filled from the brief",
            ", ".join(empty_slots),
        ))

    if unknown_slots:
        reasons.append(Reason(
            "generation.unknown_slots", Route.BLOCK,
            "model returned slots that do not exist in the selected components",
            ", ".join(unknown_slots),
        ))

    if truncated_slots:
        reasons.append(Reason(
            "generation.truncated", Route.REVIEW,
            "copy exceeded its character limit and was trimmed",
            ", ".join(truncated_slots),
        ))

    # ---- brand lint ---------------------------------------------------------
    if lint_result is not None:
        for finding in lint_result.blocks:
            reasons.append(Reason(
                f"lint.{finding.rule}", Route.BLOCK, finding.message, finding.evidence))
        for finding in lint_result.flags:
            reasons.append(Reason(
                f"lint.{finding.rule}", Route.REVIEW, finding.message, finding.evidence))

    # ---- grounding ----------------------------------------------------------
    if grounding_result is not None and not grounding_result.clean:
        if grounding_result.invented_numbers:
            reasons.append(Reason(
                "grounding.invented_figures", Route.BLOCK,
                "figures appear in the email that are not in the brief",
                ", ".join(grounding_result.invented_numbers),
            ))
        if grounding_result.invented_entities:
            reasons.append(Reason(
                "grounding.unverified_names", Route.REVIEW,
                "names or product terms appear that are not in the brief",
                ", ".join(grounding_result.invented_entities),
            ))

    # ---- voice --------------------------------------------------------------
    if voice_result is not None:
        scores = voice_result.get("scores", {})
        mean = float(voice_result.get("mean", 0))
        citations = voice_result.get("citations", {})

        if mean < THRESHOLDS["voice_mean"]:
            reasons.append(Reason(
                "voice.below_threshold", Route.REVIEW,
                f"mean tone score {mean:.2f} is below {THRESHOLDS['voice_mean']}",
                "; ".join(f"{k}: {v}" for k, v in citations.items()),
            ))
        for dimension, score in scores.items():
            if score < THRESHOLDS["voice_min_dimension"]:
                reasons.append(Reason(
                    f"voice.{dimension}", Route.BLOCK,
                    f"{dimension} scored {score}, floor is {THRESHOLDS['voice_min_dimension']}",
                    citations.get(dimension, ""),
                ))
            # A low score with no citation cannot be acted on, so it is not trusted.
            elif score < 4 and dimension not in citations:
                reasons.append(Reason(
                    "voice.uncited_score", Route.REVIEW,
                    f"{dimension} scored {score} with no supporting citation",
                ))

    if preview_iterations >= THRESHOLDS["max_preview_iterations"]:
        reasons.append(Reason(
            "preview.iteration_cap", Route.REVIEW,
            f"{preview_iterations} rounds of changes — hand to the email team",
        ))

    route = max((r.route for r in reasons), key=lambda r: SEVERITY[r], default=Route.PROCEED)
    return Decision(route=route, reasons=reasons)
