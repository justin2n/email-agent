"""
The full lifecycle, in a browser.

Four stages, matching the roadmap:

  Request       Sprint 4 - self-serve intake; the Slack thread as a web UI
  Review queue  Sprint 3 - the email team's gate
  Customer.io   Sprint 5 - draft sync, no send path
  Metrics       Sprint 6 - adoption instrumentation

Runs on Python's stdlib http.server. No Flask, no npm, no build step - a demo
that needs an install is a demo that doesn't happen.

    python3 -m src.webapp        then open http://localhost:8000

The conversation is the real `ThreadState` machine from `src/slack/app.py`.
Only the transport differs: HTTP here, Slack in production.
"""

from __future__ import annotations

import json
import os
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse

from .config import OUT as DATA_OUT, ensure_data_dirs
from .escalate import Route
from .integrations.customerio import sync_run
from .llm.client import StubClient, get_client
from .slack.app import (
    LAST_RESULT,
    ThreadState,
    handle_answers,
    handle_change_request,
    handle_new_request,
)
from .trace import metrics, record_review

# Local default is loopback-only. A host sets PORT and needs 0.0.0.0 to
# accept traffic from outside the container.
PORT = int(os.environ.get("PORT", "8000"))
HOST = os.environ.get("HOST", "0.0.0.0" if os.environ.get("PORT") else "127.0.0.1")
OUT = DATA_OUT
QUEUE_PATH = OUT / "queue.json"

ROUTE_META = {
    Route.PROCEED: ("Ready for the email team", "#0ACF83"),
    Route.REVIEW: ("Flagged for review", "#FF7262"),
    Route.REQUESTER: ("Needs more from you", "#1ABCFE"),
    Route.BLOCK: ("Blocked", "#F24E1E"),
}

EXAMPLES = [
    ("Vague ask", "Hey - can we get an email out about Dev Mode Inspect? "
                  "For developers. Needs to go Tuesday."),
    ("Complete brief",
     "We're launching Dev Mode Inspect for developers next Tuesday.\n"
     "Developers can pull production-ready specs straight from a Figma file "
     "without a designer handing anything over.\n"
     "- Copy CSS, iOS and Android values from any layer\n"
     "- See exactly what changed between versions\n"
     "- Works in the free tier for every developer seat\n"
     "Button should say \"Open Dev Mode\" and go to https://www.figma.com/dev-mode\n"
     "Send Tuesday."),
    ("Off-brand copy",
     "Webinar invite for design leaders. It's a revolutionary session on scaling "
     "design systems - genuinely game-changing stuff.\n"
     "Event: Scaling Design Systems, 2026-11-18, 11am PT, 45 minutes, online\n"
     "Button: \"Save your seat\" -> https://www.figma.com/events/scaling\n"
     "Send it this week."),
    ("Invented facts",
     "__HALLUCINATION__Product launch email to designers about auto-layout "
     "improvements.\nAuto layout now handles nested frames without manual resizing.\n"
     "- Faster on complex frames\n- Better wrapping behaviour\n- Fewer nested frames\n"
     "Ship it next week. Button \"Try auto layout\" -> https://www.figma.com/auto-layout"),
]

HALLUCINATION_FIXTURE = {
    "generate_copy": {
        "slots": {
            "headline": "Auto layout, rebuilt",
            "subhead": "Now 3.5x faster on complex frames",
            "body": "Auto layout has been rebuilt. Teams using it report a 47% "
                    "reduction in handoff time, and Acme Corp cut their design "
                    "review cycle from 5 days to 2.",
            "item_1_title": "Faster", "item_1_body": "3.5x speed on complex frames",
            "item_2_title": "Smarter", "item_2_body": "Better wrapping behaviour",
            "item_3_title": "Simpler", "item_3_body": "Fewer nested frames",
            "label": "Try auto layout", "url": "https://www.figma.com/auto-layout",
        },
        "subject_options": ["Auto layout, rebuilt from the ground up"],
        "preheader": "Faster on complex frames, with better wrapping and fewer nested frames.",
        "_confidence": 0.81,
    }
}


# ----------------------------------------------------------------------
# Queue: requests the marketer approved, waiting on the email team.
# ----------------------------------------------------------------------
def _queue() -> list[dict]:
    if not QUEUE_PATH.exists():
        return []
    try:
        return json.loads(QUEUE_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []


def _save_queue(items: list[dict]) -> None:
    QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    QUEUE_PATH.write_text(json.dumps(items, indent=2), encoding="utf-8")


def _enqueue(entry: dict) -> None:
    items = [i for i in _queue() if i["run_id"] != entry["run_id"]]
    items.insert(0, entry)
    _save_queue(items)


def _update_queue(run_id: str, **changes) -> dict | None:
    items = _queue()
    for item in items:
        if item["run_id"] == run_id:
            item.update(changes)
            _save_queue(items)
            return item
    return None


def _client(fixture=None):
    return StubClient(fixture) if fixture else get_client()


def _backend() -> str:
    return (os.environ.get("LLM_BACKEND") or "stub").lower()


def _payload(state: ThreadState, blocks: dict) -> dict:
    """Thread state, Slack blocks, and the routing detail behind them."""
    out = {
        "thread_ts": state.thread_ts,
        "status": state.status,
        "questions": state.pending_questions,
        "iterations": state.preview_iterations,
        "blocks": blocks,
    }
    result = LAST_RESULT.get(state.thread_ts)
    if result is None:
        return out

    label, color = ROUTE_META[result.decision.route]
    if result.html:
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / f"{result.run_id}.html").write_text(result.html, encoding="utf-8")

    out["result"] = {
        "run_id": result.run_id,
        "route": result.decision.route.value,
        "label": label,
        "color": color,
        "campaign_type": result.brief.campaign_type if result.brief else None,
        "audience": result.brief.audience if result.brief else None,
        "components": result.selection.components if result.selection else [],
        "path": result.selection.path if result.selection else None,
        "subject": result.subject,
        "subject_options": result.generation.subject_options if result.generation else [],
        "preheader": result.generation.preheader if result.generation else None,
        "reasons": [
            {"rule": r.rule, "route": r.route.value,
             "message": r.message, "evidence": r.evidence}
            for r in result.decision.reasons
        ],
        "duration_ms": result.trace.duration_ms if result.trace else 0,
        "has_html": bool(result.html),
    }
    return out


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    # -- GET -----------------------------------------------------------
    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/":
            page = (Path(__file__).parent / "ui.html").read_text(encoding="utf-8")
            page = page.replace("__EXAMPLES__", json.dumps(EXAMPLES))
            page = page.replace("__BACKEND__", json.dumps(_backend()))
            return self._send(200, page.encode(), "text/html; charset=utf-8")
        if path == "/api/queue":
            return self._json({"items": _queue()})
        if path == "/api/metrics":
            return self._json(self._metrics())
        if path.startswith("/preview/"):
            file = OUT / f"{path.rsplit('/', 1)[-1]}.html"
            if not file.exists():
                return self._send(404, b"no preview yet", "text/plain")
            return self._send(200, file.read_bytes(), "text/html; charset=utf-8")
        return self._send(404, b"not found", "text/plain")

    # -- POST ----------------------------------------------------------
    def do_POST(self):
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        handler = {
            "/api/thread/new": self._new,
            "/api/thread/reply": self._reply,
            "/api/thread/change": self._change,
            "/api/thread/approve": self._approve,
            "/api/review": self._review,
            "/api/sync": self._sync,
            "/api/reset": self._reset,
        }.get(path)
        if handler is None:
            return self._send(404, b"not found", "text/plain")
        try:
            return self._json(handler(body))
        except Exception as exc:
            # A demo surface must never fail silently - show the error.
            return self._json({"error": f"{type(exc).__name__}: {exc}"}, code=500)

    # -- Sprint 4: self-serve intake ------------------------------------
    def _new(self, body: dict) -> dict:
        request = str(body.get("request", "")).strip()
        if not request:
            return {"error": "empty request"}

        fixture = None
        if request.startswith("__HALLUCINATION__"):
            request = request.replace("__HALLUCINATION__", "", 1)
            fixture = HALLUCINATION_FIXTURE

        state = ThreadState(
            thread_ts=str(abs(hash(request)) % 10**10),
            channel="C-EMAIL-REQUESTS",
            requester=str(body.get("requester") or "Priya Raman"),
            raw_request=request,
        )
        state.answers["__fixture__"] = "1" if fixture else ""
        state, blocks = handle_new_request(state, client=_client(fixture))
        return _payload(state, blocks)

    def _reply(self, body: dict) -> dict:
        state = self._load(body)
        fixture = HALLUCINATION_FIXTURE if state.answers.get("__fixture__") else None
        text = str(body.get("text", ""))
        if body.get("append"):
            # Detail that isn't a schema field goes back through the request,
            # exactly as the requester would have written it the first time.
            state.raw_request += "\n- " + text.replace("\n", "\n- ")
            text = ""
        state, blocks = handle_answers(state, text, client=_client(fixture))
        return _payload(state, blocks)

    def _change(self, body: dict) -> dict:
        state = self._load(body)
        fixture = HALLUCINATION_FIXTURE if state.answers.get("__fixture__") else None
        state, blocks = handle_change_request(
            state, str(body.get("text", "")), client=_client(fixture))
        return _payload(state, blocks)

    def _approve(self, body: dict) -> dict:
        """Requester signs off. Goes to the email team's queue, never to a send."""
        state = self._load(body)
        result = LAST_RESULT.get(state.thread_ts)
        state.status = "approved"
        state.save()
        entry = {
            "run_id": state.last_run_id,
            "requester": state.requester,
            "subject": (result.subject if result else "") or "(no subject)",
            "campaign_type": result.brief.campaign_type if result and result.brief else None,
            "audience": result.brief.audience if result and result.brief else None,
            "flags": [
                {"rule": r.rule, "message": r.message, "evidence": r.evidence}
                for r in (result.decision.reasons if result else [])
                if r.route == Route.REVIEW
            ],
            "iterations": state.preview_iterations,
            "status": "awaiting_qa",
            "synced": None,
            "note": "",
        }
        _enqueue(entry)
        return {"ok": True, "queued": entry}

    # -- Sprint 3: the email team's gate --------------------------------
    def _review(self, body: dict) -> dict:
        run_id = str(body.get("run_id"))
        outcome = str(body.get("outcome"))
        note = str(body.get("note", ""))
        record_review(run_id, str(body.get("reviewer") or "email-team"), outcome, note)
        return {"ok": True, "item": _update_queue(run_id, status=outcome, note=note)}

    # -- Sprint 5: Customer.io -----------------------------------------
    def _sync(self, body: dict) -> dict:
        run_id = str(body.get("run_id"))
        result = sync_run(run_id, live=False)
        if result.get("ok"):
            _update_queue(run_id, synced=result.get("external_id"))
        payload_file = OUT / "syncs" / f"{run_id}.json"
        if payload_file.exists():
            payload = json.loads(payload_file.read_text(encoding="utf-8"))
            payload["body"] = payload.get("body", "")[:400] + " ...(truncated)"
            result["payload"] = payload
        return result

    # -- Sprint 6: adoption metrics -------------------------------------
    def _metrics(self) -> dict:
        data = metrics()
        queue = _queue()
        reviewed = [i for i in queue if i["status"] in ("accepted", "edited", "rejected")]
        accepted = [i for i in reviewed if i["status"] == "accepted"]
        data.update({
            "queue_total": len(queue),
            "queue_awaiting": len([i for i in queue if i["status"] == "awaiting_qa"]),
            "first_pass_acceptance": (round(len(accepted) / len(reviewed), 2)
                                      if reviewed else None),
            "avg_iterations": (round(sum(i["iterations"] for i in queue) / len(queue), 2)
                               if queue else 0),
            "synced": len([i for i in queue if i.get("synced")]),
            "backend": _backend(),
        })
        return data

    def _reset(self, body: dict) -> dict:
        _save_queue([])
        for pattern in ("*.html", "syncs/*.json", "threads/*.json"):
            for file in OUT.glob(pattern):
                file.unlink(missing_ok=True)
        LAST_RESULT.clear()
        return {"ok": True}

    # -- helpers --------------------------------------------------------
    def _load(self, body: dict) -> ThreadState:
        state = ThreadState.load("C-EMAIL-REQUESTS", str(body.get("thread_ts")))
        if state is None:
            raise RuntimeError("thread not found - start a new request")
        return state

    def _json(self, payload: dict, code: int = 200):
        self._send(code, json.dumps(payload).encode(), "application/json")

    def _send(self, code: int, body: bytes, content_type: str):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> int:
    ensure_data_dirs()          # a freshly-mounted volume is empty
    hosted = bool(os.environ.get("PORT"))
    url = f"http://localhost:{PORT}"
    backend = _backend()
    print(f"\n  Email Agent  ->  {'0.0.0.0:%d (hosted)' % PORT if hosted else url}")
    print(f"  backend: {backend}"
          + ("    (LLM_BACKEND=anthropic for real copy)" if backend == "stub" else ""))
    if not hosted:
        print("  Ctrl-C to stop.\n")
        try:
            webbrowser.open(url)
        except Exception:
            pass
    else:
        print()
    try:
        HTTPServer((HOST, PORT), Handler).serve_forever()
    except KeyboardInterrupt:
        print("  stopped\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
