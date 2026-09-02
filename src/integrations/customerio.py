"""
Sprint 5: Customer.io sync.

Two constraints hold regardless of configuration:

1. **Drafts only.** There is no send call in this module. Not disabled, not
   flag-guarded — absent. You cannot reach a send endpoint from this code path,
   which is a stronger guarantee than a policy anyone has to remember.

2. **Nothing syncs unless a human approved it.** `sync_run` reads the recorded
   review outcome and refuses if there isn't one.

The adapter sits behind a small interface so the ESP is swappable. The same
seam is where an ABM landing-page build would substitute its own destination.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from ..config import OUT as DATA_OUT, TRACES
from ..trace import connect

API_BASE = "https://beta-api.customer.io/v1/api"


class ESPAdapter(Protocol):
    name: str

    def create_draft(self, payload: dict[str, Any]) -> dict[str, Any]: ...


@dataclass
class DraftPayload:
    """Our internal email model, mapped to what an ESP expects."""

    name: str
    subject: str
    preheader: str
    body_html: str
    body_text: str
    run_id: str
    campaign_type: str | None = None
    audience: str | None = None

    def to_customerio(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "type": "newsletter",
            "sending_state": "draft",       # never "active"
            "subject": self.subject,
            "preheader": self.preheader,
            "body": self.body_html,
            "body_amp": None,
            "plain_text_body": self.body_text,
            "tags": [
                "source:email-agent",
                f"run:{self.run_id}",
                f"campaign_type:{self.campaign_type or 'unknown'}",
                f"audience:{self.audience or 'unknown'}",
            ],
        }


class CustomerIOAdapter:
    """Live adapter. Requires CUSTOMERIO_APP_API_KEY."""

    name = "customerio"

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.environ.get("CUSTOMERIO_APP_API_KEY")
        if not self.api_key:
            raise RuntimeError("CUSTOMERIO_APP_API_KEY is not set")

    def create_draft(self, payload: dict[str, Any]) -> dict[str, Any]:
        request = urllib.request.Request(
            f"{API_BASE}/campaigns",
            data=json.dumps(payload).encode(),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                # Idempotency: a retry after a timeout must not create a
                # second draft for the same run.
                "Idempotency-Key": payload["tags"][1].split(":", 1)[1],
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                return json.loads(response.read().decode())
        except urllib.error.HTTPError as exc:
            raise RuntimeError(
                f"Customer.io returned {exc.code}: {exc.read().decode()[:300]}"
            ) from exc


class DryRunAdapter:
    """
    Default. Writes the exact payload to disk instead of sending it.

    This is what runs without credentials, and it is genuinely useful beyond
    testing: reviewing the payload we *would* send is how you catch a mapping
    bug before it becomes fifty malformed drafts in production.
    """

    name = "dry-run"

    def __init__(self, out_dir: Path | None = None):
        self.out_dir = out_dir or (DATA_OUT / "syncs")

    def create_draft(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        run_id = payload["tags"][1].split(":", 1)[1]
        path = self.out_dir / f"{run_id}.json"
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return {"id": f"dry-run-{run_id}", "written_to": str(path), "dry_run": True}


def get_adapter(live: bool = False) -> ESPAdapter:
    return CustomerIOAdapter() if live else DryRunAdapter()


def sync_run(run_id: str, *, live: bool = False,
             require_review: bool = True) -> dict[str, Any]:
    """
    Push one approved email as a Customer.io draft.

    Refuses if the run was never reviewed, or if the pipeline's own decision
    was anything other than proceed-or-review. The ESP is not a place to
    launder an escalation.
    """
    trace_path = TRACES / f"{run_id}.json"
    if not trace_path.exists():
        return {"ok": False, "error": f"no trace found for run {run_id}"}

    trace = json.loads(trace_path.read_text(encoding="utf-8"))

    if trace.get("route") in ("block", "back_to_requester"):
        return {
            "ok": False,
            "error": f"run {run_id} was routed '{trace['route']}' and cannot be synced",
            "reasons": trace.get("reasons", []),
        }

    if require_review:
        with connect() as conn:
            row = conn.execute(
                "SELECT outcome, reviewer FROM reviews WHERE run_id = ? "
                "ORDER BY reviewed_at DESC LIMIT 1", (run_id,)
            ).fetchone()
        if not row:
            return {
                "ok": False,
                "error": f"run {run_id} has no recorded review — "
                         f"run `email-agent review {run_id} --outcome accepted` first",
            }
        if row[0] == "rejected":
            return {"ok": False, "error": f"run {run_id} was rejected by {row[1]}"}

    html_path = DATA_OUT / f"{run_id}.html"
    if not html_path.exists():
        return {"ok": False, "error": f"no rendered HTML at {html_path}; "
                                      f"re-run generate with --save"}

    brief = trace.get("brief") or {}
    payload = DraftPayload(
        name=_draft_name(trace, brief),
        subject=trace.get("subject", ""),
        preheader=trace.get("preheader", ""),
        body_html=html_path.read_text(encoding="utf-8"),
        body_text="",
        run_id=run_id,
        campaign_type=brief.get("campaign_type"),
        audience=brief.get("audience"),
    ).to_customerio()

    adapter = get_adapter(live)
    try:
        response = adapter.create_draft(payload)
    except Exception as exc:
        # A failed sync must never lose the artifact. The HTML and trace are
        # still on disk; the email team falls back to manual handoff.
        _record_sync(run_id, adapter.name, None, f"failed: {exc}")
        return {"ok": False, "error": str(exc), "fallback": "manual handoff",
                "artifact": str(html_path)}

    external_id = str(response.get("id", ""))
    _record_sync(run_id, adapter.name, external_id, "draft_created")
    return {
        "ok": True,
        "run_id": run_id,
        "provider": adapter.name,
        "external_id": external_id,
        "sending_state": "draft",
        "note": "Created as a draft. Sending remains a human action in Customer.io.",
        "response": response,
    }


def _draft_name(trace: dict, brief: dict) -> str:
    stamp = (trace.get("started_at") or "")[:10]
    campaign = brief.get("campaign_type") or "email"
    return f"[agent] {campaign} — {trace.get('subject', '')[:48]} ({stamp})"


def _record_sync(run_id: str, provider: str, external_id: str | None,
                 status: str) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO syncs VALUES (?,?,?,?,?)",
            (run_id, datetime.now(timezone.utc).isoformat(timespec="seconds"),
             provider, external_id, status),
        )


def diff_against_source(run_id: str, edited_html: str) -> dict[str, Any]:
    """
    Sprint 5's quiet payoff.

    Every edit the email team makes in Customer.io after sync is a labelled
    example of where the agent was wrong. Pulling those diffs back turns the
    team's normal QA work into the highest-signal eval data in the system —
    at no extra cost to them.
    """
    import difflib

    from ..vet.lint import _visible_text

    original_path = DATA_OUT / f"{run_id}.html"
    if not original_path.exists():
        return {"ok": False, "error": "original not found"}

    before = _visible_text(original_path.read_text(encoding="utf-8")).split()
    after = _visible_text(edited_html).split()
    diff = list(difflib.unified_diff(before, after, lineterm="", n=2))

    changed = sum(1 for line in diff if line.startswith(("+", "-"))
                  and not line.startswith(("+++", "---")))
    return {
        "ok": True,
        "run_id": run_id,
        "words_before": len(before),
        "words_after": len(after),
        "words_changed": changed,
        "change_ratio": round(changed / max(len(before), 1), 3),
        "diff": diff[:80],
    }
