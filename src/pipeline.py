"""
The orchestrator.

Six steps, explicit contracts, one escalation decision at the end. Deliberately
a plain function rather than a framework: this is ~150 lines of sequencing, and
an agent framework here would hide the token flow exactly where it needs to be
visible for eval work.

Flow:

    raw request
      -> extract        (model)   messy text becomes fields
      -> validate       (code)    is it complete? is it valid?
      -> clarify        (model)   phrase the gaps, if any        [may stop]
      -> select         (rules)   which components               [model fallback]
      -> generate       (model)   fill the slots
      -> assemble       (code)    Jinja2 -> email-safe HTML
      -> lint           (code)    brand rules
      -> grounding      (code)    did it invent anything?
      -> voice          (model)   does it sound like us?
      -> decide         (code)    proceed / review / requester / block

The model appears four times. Everything that determines whether an email ships
is in the code steps.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import escalate
from .config import config_fingerprint
from .escalate import Decision, Route
from .llm.client import BaseClient, LLMError, get_client
from .models.brief import Brief
from .render.assemble import RenderResult, assemble
from .steps.generate import GenerationError, GenerationResult, generate_copy
from .steps.intake import clarify_gaps, extract_brief
from .steps.select import SelectionError, SelectionResult, select_components, unfillable
from .trace import StepRecord, Trace, new_trace, persist, timed
from .vet.grounding import GroundingResult, check_grounding
from .vet.lint import LintResult, lint
from .vet.voice import VoiceResult, vet_voice


@dataclass
class PipelineResult:
    run_id: str
    decision: Decision
    brief: Brief | None = None
    questions: list[str] = field(default_factory=list)
    selection: SelectionResult | None = None
    generation: GenerationResult | None = None
    render: RenderResult | None = None
    lint_result: LintResult | None = None
    grounding: GroundingResult | None = None
    voice: VoiceResult | None = None
    trace: Trace | None = None
    error: str | None = None

    @property
    def html(self) -> str | None:
        return self.render.html if self.render else None

    @property
    def subject(self) -> str | None:
        return self.generation.subject if self.generation else None

    def status_line(self) -> str:
        return f"[{self.decision.route.value}] run {self.run_id}"


def run(
    raw_request: str,
    *,
    client: BaseClient | None = None,
    requester: str | None = None,
    source: str = "cli",
    answers: dict[str, str] | None = None,
    clarify_rounds: int = 0,
    persist_run: bool = True,
    utm_campaign: str = "email",
) -> PipelineResult:
    client = client or get_client()
    trace = new_trace(raw_request, source=source, requester=requester)

    try:
        return _run(
            raw_request, client, trace, requester, source,
            answers or {}, clarify_rounds, persist_run, utm_campaign,
        )
    except (LLMError, SelectionError, GenerationError) as exc:
        # Known failure modes stop cleanly with a human-readable reason rather
        # than a stack trace and a half-built email.
        trace.error = f"{type(exc).__name__}: {exc}"
        trace.route = Route.BLOCK.value
        decision = Decision(route=Route.BLOCK, reasons=[
            escalate.Reason("pipeline.step_failed", Route.BLOCK, str(exc), type(exc).__name__)
        ])
        trace.reasons = [vars(r) | {"route": r.route.value} for r in decision.reasons]
        path = trace.write()
        if persist_run:
            persist(trace, path)
        return PipelineResult(run_id=trace.run_id, decision=decision,
                              trace=trace, error=str(exc))


def _run(raw_request, client, trace, requester, source,
         answers, clarify_rounds, persist_run, utm_campaign) -> PipelineResult:

    # -- 1. extract -------------------------------------------------------
    with timed(trace, "extract") as rec:
        extraction = extract_brief(raw_request, client, requester=requester, source=source)
        brief = extraction.brief
        rec.model = extraction.model
        rec.detail = {"confidence": extraction.confidence, "retried": extraction.retried}

    if answers:
        from .steps.intake import apply_answers
        brief = apply_answers(brief, answers)

    trace.brief = brief.to_dict()

    # -- 2. validate (code) -----------------------------------------------
    with timed(trace, "validate") as rec:
        missing = brief.missing_fields()
        issues = brief.validate()
        rec.detail = {"missing": missing, "issues": [str(i) for i in issues]}

    # -- 3. clarify, and stop if the brief cannot support an email ---------
    questions: list[str] = []
    if missing:
        with timed(trace, "clarify") as rec:
            clarification = clarify_gaps(brief, client)
            questions = clarification.questions
            rec.model = clarification.model
            rec.detail = {"questions": questions}

        decision = escalate.decide(
            missing_fields=missing,
            validation_issues=issues,
            extraction_confidence=extraction.confidence,
            clarify_rounds=clarify_rounds,
        )
        return _finish(trace, decision, persist_run,
                       PipelineResult(run_id=trace.run_id, decision=decision,
                                      brief=brief, questions=questions, trace=trace))

    # -- 4. select components (rules first) --------------------------------
    with timed(trace, "select") as rec:
        selection = select_components(brief, client)
        rec.model = selection.model
        rec.detail = {
            "path": selection.path,
            "components": selection.components,
            "confidence": selection.confidence,
        }
    gaps = unfillable(selection.components, brief)

    # -- 5. generate copy ---------------------------------------------------
    with timed(trace, "generate") as rec:
        generation = generate_copy(brief, selection.components, client)
        rec.model = generation.model
        rec.detail = {
            "confidence": generation.confidence,
            "empty_slots": generation.empty_slots,
            "truncated_slots": generation.truncated_slots,
            "unknown_slots": generation.unknown_slots,
        }
    trace.subject = generation.subject
    trace.preheader = generation.preheader

    # -- 6. assemble (pure code) -------------------------------------------
    with timed(trace, "assemble") as rec:
        rendered = assemble(
            selection.components, generation.slots,
            generation.subject, generation.preheader,
            utm_campaign=utm_campaign,
        )
        rec.detail = {"renderer": rendered.renderer, "bytes": len(rendered.html)}
    trace.components = selection.components

    # -- 7. brand lint (pure code) -----------------------------------------
    with timed(trace, "lint") as rec:
        lint_result = lint(rendered.html, generation.subject, generation.preheader)
        rec.detail = {
            "summary": lint_result.summary(),
            "findings": [str(f) for f in lint_result.findings],
        }

    # -- 8. grounding (pure code) ------------------------------------------
    with timed(trace, "grounding") as rec:
        grounding = check_grounding(
            rendered.html, generation.subject, generation.preheader, brief)
        rec.detail = {
            "summary": grounding.summary(),
            "invented_numbers": grounding.invented_numbers,
            "invented_entities": grounding.invented_entities,
        }

    # -- 9. voice (model, advisory only) -----------------------------------
    with timed(trace, "voice") as rec:
        voice = vet_voice(rendered.html, generation.subject,
                          generation.preheader, brief.audience, client)
        rec.model = voice.model
        rec.detail = voice.to_dict()

    # -- 10. decide (pure code) --------------------------------------------
    decision = escalate.decide(
        missing_fields=[],
        validation_issues=issues,
        extraction_confidence=extraction.confidence,
        selection_path=selection.path,
        selection_confidence=selection.confidence,
        unfillable_components=gaps,
        generation_confidence=generation.confidence,
        empty_slots=generation.empty_slots,
        unknown_slots=generation.unknown_slots,
        truncated_slots=generation.truncated_slots,
        lint_result=lint_result,
        grounding_result=grounding,
        voice_result=voice.to_dict() if voice.available else None,
        clarify_rounds=clarify_rounds,
    )

    if not voice.available:
        decision.reasons.append(escalate.Reason(
            "voice.unavailable", Route.REVIEW,
            "tone check could not run — a failed check is not a pass",
        ))
        if decision.route == Route.PROCEED:
            decision.route = Route.REVIEW

    return _finish(trace, decision, persist_run, PipelineResult(
        run_id=trace.run_id, decision=decision, brief=brief,
        selection=selection, generation=generation, render=rendered,
        lint_result=lint_result, grounding=grounding, voice=voice, trace=trace,
    ))


def _finish(trace: Trace, decision: Decision, persist_run: bool,
            result: PipelineResult) -> PipelineResult:
    trace.route = decision.route.value
    trace.reasons = [
        {"rule": r.rule, "route": r.route.value, "message": r.message, "evidence": r.evidence}
        for r in decision.reasons
    ]
    trace.duration_ms = sum(s.duration_ms for s in trace.steps)
    path = trace.write()
    if persist_run:
        persist(trace, path)
    return result
