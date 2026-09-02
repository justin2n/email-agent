"""
Command line interface.

    python -m src.cli generate --request "..."      run the pipeline
    python -m src.cli generate --file req.txt --open
    python -m src.cli demo                          the four demo scenarios
    python -m src.cli metrics                       adoption dashboard
    python -m src.cli review <run_id> --outcome edited --note "..."
    python -m src.cli sync <run_id>                 push to Customer.io (dry run by default)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import OUT as DATA_OUT
from .escalate import Route
from .llm.client import get_client
from .pipeline import PipelineResult, run
from .trace import metrics, record_review

OUT = DATA_OUT

GREEN, YELLOW, RED, BLUE, DIM, RESET = (
    "\033[32m", "\033[33m", "\033[31m", "\033[36m", "\033[2m", "\033[0m"
)
ARROW = " \u203a "
ROUTE_COLOR = {
    Route.PROCEED: GREEN,
    Route.REVIEW: YELLOW,
    Route.REQUESTER: BLUE,
    Route.BLOCK: RED,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="email-agent")
    sub = parser.add_subparsers(dest="command", required=True)

    gen = sub.add_parser("generate", help="run a request through the pipeline")
    src = gen.add_mutually_exclusive_group(required=True)
    src.add_argument("--request", help="the request text")
    src.add_argument("--file", help="path to a file containing the request")
    gen.add_argument("--requester", default=None)
    gen.add_argument("--backend", default=None, help="stub (default) or anthropic")
    gen.add_argument("--json", action="store_true", help="machine-readable output")
    gen.add_argument("--save", action="store_true", help="write the HTML to out/")

    sub.add_parser("demo", help="run the four demo scenarios")
    sub.add_parser("metrics", help="print the adoption dashboard")

    rev = sub.add_parser("review", help="record an email team review")
    rev.add_argument("run_id")
    rev.add_argument("--reviewer", default="email-team")
    rev.add_argument("--outcome", choices=["accepted", "edited", "rejected"], required=True)
    rev.add_argument("--note", default="")

    syn = sub.add_parser("sync", help="push an approved email to Customer.io")
    syn.add_argument("run_id")
    syn.add_argument("--live", action="store_true", help="actually call the API")

    args = parser.parse_args(argv)

    if args.command == "generate":
        return _generate(args)
    if args.command == "demo":
        return _demo()
    if args.command == "metrics":
        print(json.dumps(metrics(), indent=2))
        return 0
    if args.command == "review":
        record_review(args.run_id, args.reviewer, args.outcome, args.note)
        print(f"recorded: {args.run_id} -> {args.outcome}")
        return 0
    if args.command == "sync":
        return _sync(args)
    return 1


def _generate(args) -> int:
    text = Path(args.file).read_text(encoding="utf-8") if args.file else args.request
    client = get_client(args.backend)
    result = run(text, client=client, requester=args.requester)

    saved_path = None
    if args.save and result.html:
        OUT.mkdir(exist_ok=True)
        saved_path = OUT / f"{result.run_id}.html"
        saved_path.write_text(result.html, encoding="utf-8")

    if args.json:
        # --save must not print a stray line after the JSON block, or piping
        # the output into anything breaks.
        print(json.dumps({
            "run_id": result.run_id,
            "html_path": str(saved_path) if saved_path else None,
            "route": result.decision.route.value,
            "subject": result.subject,
            "questions": result.questions,
            "reasons": [
                {"rule": r.rule, "route": r.route.value, "message": r.message,
                 "evidence": r.evidence}
                for r in result.decision.reasons
            ],
        }, indent=2))
    else:
        _print(result)
        if saved_path:
            print(f"  html: {saved_path}\n")

    return 0 if result.decision.route == Route.PROCEED else 2


def _print(result: PipelineResult) -> None:
    route = result.decision.route
    color = ROUTE_COLOR.get(route, "")
    print()
    print(f"  {color}\u25cf {route.value.upper().replace('_', ' ')}{RESET}"
          f"  {DIM}run {result.run_id}{RESET}")

    if result.brief:
        b = result.brief
        print(f"  {DIM}brief:{RESET} {b.campaign_type or '?'} \u2192 {b.audience or '?'}")

    if result.selection:
        s = result.selection
        marker = f"{GREEN}rule{RESET}" if s.path == "rule" else f"{YELLOW}model{RESET}"
        chain = ARROW.join(s.components)
        print(f"  {DIM}components ({marker}{DIM}):{RESET} {chain}")

    if result.subject:
        print(f"  {DIM}subject:{RESET} {result.subject}")

    if result.questions:
        print(f"\n  {BLUE}Questions for the requester:{RESET}")
        for q in result.questions:
            print("    \u2022 " + q)

    if result.decision.reasons:
        print(f"\n  {DIM}Why:{RESET}")
        print(result.decision.explain())
    else:
        print(f"\n  {GREEN}No issues found.{RESET}")

    if result.trace:
        total = result.trace.duration_ms
        steps = " ".join(f"{s.name}:{s.duration_ms}ms" for s in result.trace.steps)
        print(f"\n  {DIM}{total}ms total \u2014 {steps}{RESET}")
        print(f"  {DIM}trace: traces/{result.run_id}.json{RESET}")
    print()


def _demo() -> int:
    from .demo import run_demo
    return run_demo()


def _sync(args) -> int:
    from .integrations.customerio import sync_run
    result = sync_run(args.run_id, live=args.live)
    print(json.dumps(result, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
