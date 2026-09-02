"""
Sprint 4: self-serve intake.

Where the hours actually get saved. Sprints 1-3 remove the email team's build
time; this removes the latency and rework that make up most of the two-week
turnaround.

The loop:

    stakeholder posts a request in-channel
      -> agent replies in-thread with any gaps          (minutes, not days)
      -> stakeholder answers in the same thread
      -> agent posts a rendered preview
      -> approve / request changes, up to the iteration cap
      -> on approval, routed to the email team with brief + preview + trace

Requires `pip install slack-bolt`. `ThreadState` and `handle_*` are pure
functions of state, so the conversation logic is unit-tested without Slack.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from ..config import OUT as DATA_OUT
from ..escalate import THRESHOLDS, Route
from ..llm.client import get_client
from ..models.brief import FIELD_LABELS  # noqa: F401
from ..pipeline import PipelineResult, run

STATE_DIR = DATA_OUT / "threads"

# Last pipeline result per thread. The Slack UI only needs the blocks, but
# other surfaces (the web demo, debugging) want the routing detail behind them.
# Kept out of ThreadState so it is never serialised to disk.
LAST_RESULT: dict[str, "PipelineResult"] = {}


@dataclass
class ThreadState:
    """One request, one Slack thread. Persisted so restarts don't lose context."""

    thread_ts: str
    channel: str
    requester: str
    raw_request: str
    answers: dict[str, str] = field(default_factory=dict)
    pending_questions: list[str] = field(default_factory=list)
    pending_fields: list[str] = field(default_factory=list)
    clarify_rounds: int = 0
    preview_iterations: int = 0
    last_run_id: str | None = None
    status: str = "new"   # new | awaiting_answers | previewing | approved | escalated

    def path(self) -> Path:
        return STATE_DIR / f"{self.channel}-{self.thread_ts}.json"

    def save(self) -> None:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        self.path().write_text(json.dumps(self.__dict__, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, channel: str, thread_ts: str) -> "ThreadState | None":
        path = STATE_DIR / f"{channel}-{thread_ts}.json"
        if not path.exists():
            return None
        return cls(**json.loads(path.read_text(encoding="utf-8")))


def handle_new_request(state: ThreadState, client=None) -> tuple[ThreadState, dict]:
    """First pass. Either asks for gaps or returns a preview."""
    result = run(
        state.raw_request,
        client=client or get_client(),
        requester=state.requester,
        source="slack",
        clarify_rounds=state.clarify_rounds,
    )
    return _advance(state, result)


def handle_answers(state: ThreadState, reply_text: str, client=None) -> tuple[ThreadState, dict]:
    """
    Threaded replies merged back into the brief.

    Answers are matched to the fields we asked about, in order. Requesters
    answer in prose, not JSON, so we keep the mapping simple and re-ask
    anything still missing rather than guessing.
    """
    from ..steps.intake import match_answers

    lines = [l.strip("-\u2022 ").strip() for l in reply_text.splitlines() if l.strip()]
    state.answers.update(match_answers(state.pending_fields, lines))

    state.clarify_rounds += 1
    result = run(
        state.raw_request,
        client=client or get_client(),
        requester=state.requester,
        source="slack",
        answers=state.answers,
        clarify_rounds=state.clarify_rounds,
    )
    return _advance(state, result)


def handle_change_request(state: ThreadState, change_text: str,
                          client=None) -> tuple[ThreadState, dict]:
    """Regenerate with the requested change appended to the brief."""
    state.preview_iterations += 1
    if state.preview_iterations >= THRESHOLDS["max_preview_iterations"]:
        state.status = "escalated"
        state.save()
        return state, _blocks_escalated(state)

    augmented = f"{state.raw_request}\n\nRequested change: {change_text}"
    result = run(
        augmented,
        client=client or get_client(),
        requester=state.requester,
        source="slack",
        answers=state.answers,
        clarify_rounds=state.clarify_rounds,
    )
    return _advance(state, result)


# Escalations that send a request back but have no missing *schema* field.
# Without these the requester gets "a few things before I can build this"
# followed by nothing — a dead end, and the fastest way to lose their trust.
SLOT_QUESTIONS = {
    "item_1_title": "This layout highlights three things the feature does. "
                    "Can you give me three short points?",
    "item_2_title": None,   # covered by the question above
    "item_3_title": None,
    "item_1_body": None,
    "item_2_body": None,
    "item_3_body": None,
    "quote": "Can you paste the approved customer quote, and who it's from?",
    "attribution_name": None,
    "resource_title": "What's the resource called, and what's the link?",
    "resource_url": None,
    "image_url": "This layout needs an image. Can you share the asset and a "
                 "one-line description of it for screen readers?",
    "image_alt": None,
    "event_name": "What's the event called?",
    "event_date": "What date and time, including time zone?",
    "event_time": None,
}


def questions_from_reasons(result: PipelineResult) -> list[str]:
    """
    Turn escalation reasons into something a marketer can act on.

    The router speaks in rules and slot ids because that is what makes it
    testable. This translates that into a question, so the requester is never
    shown `item_1_title` or handed an empty list.
    """
    asked: list[str] = []
    for reason in result.decision.reasons:
        if reason.rule == "generation.empty_slots":
            for slot in [s.strip() for s in reason.evidence.split(",")]:
                question = SLOT_QUESTIONS.get(slot)
                if question and question not in asked:
                    asked.append(question)
        elif reason.rule == "selection.unfillable":
            for slot, question in SLOT_QUESTIONS.items():
                if question and slot in reason.evidence and question not in asked:
                    asked.append(question)
    if not asked:
        # Last resort: say what happened in plain words rather than nothing.
        asked = [
            f"{r.message}" for r in result.decision.reasons if r.route == Route.REQUESTER
        ] or ["I need a bit more detail before I can build this — "
              "what's the main thing you want the email to say?"]
    return asked[:5]


def _advance(state: ThreadState, result: PipelineResult) -> tuple[ThreadState, dict]:
    state.last_run_id = result.run_id
    LAST_RESULT[state.thread_ts] = result
    route = result.decision.route

    if route == Route.REQUESTER:
        missing = result.brief.missing_fields() if result.brief else []
        state.pending_fields = missing
        # A schema gap produces questions upstream. Anything else (a layout the
        # brief can't fill) is translated here.
        state.pending_questions = result.questions or questions_from_reasons(result)
        state.status = "awaiting_answers"
        state.save()
        return state, _blocks_questions(state)

    if route == Route.BLOCK:
        state.status = "escalated"
        state.save()
        return state, _blocks_blocked(state, result)

    state.status = "previewing"
    state.save()
    return state, _blocks_preview(state, result)


# ----------------------------------------------------------------------
# Slack Block Kit payloads. Plain dicts so they're testable without Slack.
# ----------------------------------------------------------------------
def _blocks_questions(state: ThreadState) -> dict:
    lines = "\n".join(f"• {q}" for q in state.pending_questions)
    return {
        "text": "A few things before I can build this",
        "blocks": [
            {"type": "section", "text": {"type": "mrkdwn",
             "text": f"*A few things before I can build this*\n{lines}"}},
            {"type": "context", "elements": [{"type": "mrkdwn",
             "text": "Reply in this thread — one answer per line, same order."}]},
        ],
    }


def _blocks_preview(state: ThreadState, result: PipelineResult) -> dict:
    flags = [r for r in result.decision.reasons if r.route == Route.REVIEW]
    note = (f"\n\n_{len(flags)} thing(s) flagged for the email team to look at._"
            if flags else "")
    return {
        "text": f"Preview ready: {result.subject}",
        "blocks": [
            {"type": "section", "text": {"type": "mrkdwn",
             "text": f"*Preview ready*\n*Subject:* {result.subject}"
                     f"\n*Preheader:* {result.generation.preheader if result.generation else ''}"
                     f"{note}"}},
            {"type": "actions", "elements": [
                {"type": "button", "style": "primary",
                 "text": {"type": "plain_text", "text": "Looks good"},
                 "action_id": "approve", "value": result.run_id},
                {"type": "button",
                 "text": {"type": "plain_text", "text": "Request changes"},
                 "action_id": "request_changes", "value": result.run_id},
                {"type": "button",
                 "text": {"type": "plain_text", "text": "Open preview"},
                 "action_id": "open_preview", "url": _preview_url(result.run_id)},
            ]},
            {"type": "context", "elements": [{"type": "mrkdwn",
             "text": f"Run `{result.run_id}` · iteration {state.preview_iterations + 1}"}]},
        ],
    }


def _blocks_blocked(state: ThreadState, result: PipelineResult) -> dict:
    reasons = "\n".join(f"• {r.message}" + (f" (`{r.evidence}`)" if r.evidence else "")
                        for r in result.decision.reasons[:5])
    return {
        "text": "Stopped — needs a person",
        "blocks": [
            {"type": "section", "text": {"type": "mrkdwn",
             "text": f"*I stopped rather than guessing.*\n{reasons}"}},
            {"type": "context", "elements": [{"type": "mrkdwn",
             "text": f"Passed to the email team. Run `{result.run_id}`."}]},
        ],
    }


def _blocks_escalated(state: ThreadState) -> dict:
    return {
        "text": "Handing this to the email team",
        "blocks": [{"type": "section", "text": {"type": "mrkdwn",
                    "text": f"*Handing this to the email team.*\nWe've been round "
                            f"{state.preview_iterations} times — faster for a human "
                            f"to take it from here."}}],
    }


def _preview_url(run_id: str) -> str:
    import os
    base = os.environ.get("PREVIEW_BASE_URL", "https://email-agent.internal/preview")
    return f"{base}/{run_id}"


# ----------------------------------------------------------------------
# Slack wiring. Imported only when slack_bolt is installed.
# ----------------------------------------------------------------------
def build_app(handler_factory: Callable[[], Any] | None = None):  # pragma: no cover
    from slack_bolt import App

    app = App(token=_env("SLACK_BOT_TOKEN"), signing_secret=_env("SLACK_SIGNING_SECRET"))

    @app.event("app_mention")
    def on_mention(event, say):
        state = ThreadState(
            thread_ts=event.get("thread_ts") or event["ts"],
            channel=event["channel"],
            requester=event["user"],
            raw_request=event["text"],
        )
        _, blocks = handle_new_request(state)
        say(thread_ts=state.thread_ts, **blocks)

    @app.event("message")
    def on_thread_reply(event, say):
        if not event.get("thread_ts") or event.get("bot_id"):
            return
        state = ThreadState.load(event["channel"], event["thread_ts"])
        if not state or state.status != "awaiting_answers":
            return
        _, blocks = handle_answers(state, event["text"])
        say(thread_ts=state.thread_ts, **blocks)

    @app.action("approve")
    def on_approve(ack, body, say):
        ack()
        state = ThreadState.load(body["channel"]["id"],
                                 body["message"]["thread_ts"])
        if state:
            state.status = "approved"
            state.save()
        say(thread_ts=body["message"]["thread_ts"],
            text="Approved — sent to the email team for final QA.")

    @app.action("request_changes")
    def on_changes(ack, body, client):
        ack()
        client.views_open(trigger_id=body["trigger_id"], view={
            "type": "modal", "callback_id": "changes_modal",
            "title": {"type": "plain_text", "text": "Request changes"},
            "submit": {"type": "plain_text", "text": "Send"},
            "blocks": [{"type": "input", "block_id": "change",
                        "label": {"type": "plain_text", "text": "What should change?"},
                        "element": {"type": "plain_text_input", "multiline": True,
                                    "action_id": "text"}}],
        })

    return app


def _env(name: str) -> str:  # pragma: no cover
    import os
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} is not set")
    return value
