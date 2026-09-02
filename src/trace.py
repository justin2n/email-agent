"""
Run tracing and persistence.

Every run writes a complete JSON trace: inputs, which prompts fired, what each
step returned, timings, token counts, and the escalation decision with its
reasons. A run can be reconstructed entirely from disk.

This is not observability theatre. It is what makes the eval loop possible —
when the email team edits a draft, the trace tells you which step produced the
thing they changed.
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import DB_FILE, TRACES, config_fingerprint

DB_PATH = DB_FILE


@dataclass
class StepRecord:
    name: str
    duration_ms: int
    model: str = "none"
    input_tokens: int = 0
    output_tokens: int = 0
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass
class Trace:
    run_id: str
    started_at: str
    source: str
    requester: str | None
    raw_request: str
    steps: list[StepRecord] = field(default_factory=list)
    brief: dict[str, Any] | None = None
    components: list[str] = field(default_factory=list)
    subject: str = ""
    preheader: str = ""
    route: str = ""
    reasons: list[dict[str, str]] = field(default_factory=list)
    error: str | None = None
    duration_ms: int = 0
    config: dict[str, str] = field(default_factory=config_fingerprint)

    def add(self, record: StepRecord) -> None:
        self.steps.append(record)

    @property
    def total_tokens(self) -> int:
        return sum(s.input_tokens + s.output_tokens for s in self.steps)

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(asdict(self))

    def write(self) -> Path:
        TRACES.mkdir(parents=True, exist_ok=True)
        path = TRACES / f"{self.run_id}.json"
        path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
        return path


def new_trace(raw_request: str, *, source: str = "cli",
              requester: str | None = None) -> Trace:
    return Trace(
        run_id=uuid.uuid4().hex[:12],
        started_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        source=source,
        requester=requester,
        raw_request=raw_request,
    )


class timed:
    """`with timed(trace, "step_name") as t:` — records duration even on failure."""

    def __init__(self, trace: Trace, name: str):
        self.trace = trace
        self.name = name
        self.record = StepRecord(name=name, duration_ms=0)

    def __enter__(self) -> StepRecord:
        self._start = time.perf_counter()
        return self.record

    def __exit__(self, *exc) -> bool:
        self.record.duration_ms = int((time.perf_counter() - self._start) * 1000)
        self.trace.add(self.record)
        return False


def _jsonable(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return _jsonable(asdict(value))
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if hasattr(value, "value") and hasattr(value, "name"):   # Enum
        return value.value
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


# ----------------------------------------------------------------------
# SQLite. One file, no server, backs up with cp.
# ----------------------------------------------------------------------
SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id           TEXT PRIMARY KEY,
    started_at       TEXT NOT NULL,
    source           TEXT,
    requester        TEXT,
    campaign_type    TEXT,
    audience         TEXT,
    subject          TEXT,
    route            TEXT,
    reason_count     INTEGER,
    duration_ms      INTEGER,
    total_tokens     INTEGER,
    selection_path   TEXT,
    trace_path       TEXT
);
CREATE TABLE IF NOT EXISTS reviews (
    run_id           TEXT,
    reviewed_at      TEXT,
    reviewer         TEXT,
    outcome          TEXT,     -- accepted | edited | rejected
    edit_summary     TEXT,
    FOREIGN KEY(run_id) REFERENCES runs(run_id)
);
CREATE TABLE IF NOT EXISTS syncs (
    run_id           TEXT,
    synced_at        TEXT,
    provider         TEXT,
    external_id      TEXT,
    status           TEXT,
    FOREIGN KEY(run_id) REFERENCES runs(run_id)
);
"""


def connect(path: Path | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(path or DB_PATH)
    conn.executescript(SCHEMA)
    return conn


def persist(trace: Trace, trace_path: Path, db: Path | None = None) -> None:
    brief = trace.brief or {}
    selection = next((s.detail.get("path") for s in trace.steps if s.name == "select"), None)
    with connect(db) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                trace.run_id, trace.started_at, trace.source, trace.requester,
                brief.get("campaign_type"), brief.get("audience"), trace.subject,
                trace.route, len(trace.reasons), trace.duration_ms,
                trace.total_tokens, selection, str(trace_path),
            ),
        )


def record_review(run_id: str, reviewer: str, outcome: str,
                  edit_summary: str = "", db: Path | None = None) -> None:
    """
    The highest-signal data in the system.

    Every edit the email team makes is a labelled example of where the agent was
    wrong — produced for free by work they were doing anyway. These rows feed the
    eval suite.
    """
    with connect(db) as conn:
        conn.execute(
            "INSERT INTO reviews VALUES (?,?,?,?,?)",
            (run_id, datetime.now(timezone.utc).isoformat(timespec="seconds"),
             reviewer, outcome, edit_summary),
        )


def metrics(db: Path | None = None) -> dict[str, Any]:
    """Backs the adoption dashboard from requirements.md section 6."""
    with connect(db) as conn:
        total = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
        by_route = dict(conn.execute(
            "SELECT route, COUNT(*) FROM runs GROUP BY route").fetchall())
        by_path = dict(conn.execute(
            "SELECT selection_path, COUNT(*) FROM runs GROUP BY selection_path").fetchall())
        reviews = dict(conn.execute(
            "SELECT outcome, COUNT(*) FROM reviews GROUP BY outcome").fetchall())
        avg_ms = conn.execute("SELECT AVG(duration_ms) FROM runs").fetchone()[0] or 0

    accepted = reviews.get("accepted", 0)
    reviewed = sum(reviews.values())
    return {
        "runs_total": total,
        "by_route": by_route,
        "by_selection_path": by_path,
        "reviews": reviews,
        "first_pass_acceptance": round(accepted / reviewed, 3) if reviewed else None,
        "avg_duration_ms": round(avg_ms),
        "proceed_rate": round(by_route.get("proceed", 0) / total, 3) if total else None,
    }
