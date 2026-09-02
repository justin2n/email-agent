"""
Eval runner.

    python evals/run.py                 run everything
    python evals/run.py --family messy  run one family
    python evals/run.py --baseline      record the current scores as the floor
    python evals/run.py --check         fail if any family drops below the floor

`--check` is what CI runs on every prompt or rule change. A prompt edit that
improves one family and quietly breaks another is the failure mode this exists
to catch.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from evals.cases import ALL_CASES, Case, by_family          # noqa: E402
from src.escalate import Route                              # noqa: E402
from src.llm.client import StubClient                       # noqa: E402
from src.pipeline import run                                # noqa: E402

BASELINE_PATH = Path(__file__).parent / "baseline.json"

GREEN, RED, YELLOW, DIM, BOLD, RESET = (
    "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[1m", "\033[0m"
)


@dataclass
class CaseResult:
    case: Case
    passed: bool
    route: str
    failures: list[str] = field(default_factory=list)
    run_id: str = ""


def evaluate(case: Case) -> CaseResult:
    client = StubClient(case.fixture) if case.fixture else StubClient()
    result = run(case.request, client=client, source="eval", persist_run=False)

    failures: list[str] = []
    fired = {r.rule for r in result.decision.reasons}

    if result.decision.route not in case.routes():
        failures.append(
            f"route was {result.decision.route.value}, expected "
            f"{'/'.join(r.value for r in case.routes())}"
        )

    for rule in case.expect_rules:
        if not any(f == rule or f.startswith(rule) for f in fired):
            failures.append(f"expected rule '{rule}' did not fire")

    for rule in case.forbid_rules:
        if any(f == rule or f.startswith(rule) for f in fired):
            failures.append(f"forbidden rule '{rule}' fired")

    if case.expect_selection_path and result.selection:
        if result.selection.path != case.expect_selection_path:
            failures.append(
                f"selection path was '{result.selection.path}', "
                f"expected '{case.expect_selection_path}'"
            )

    if case.expect_components and result.selection:
        if result.selection.components != case.expect_components:
            failures.append(
                f"components were {result.selection.components}, "
                f"expected {case.expect_components}"
            )

    # The key assertion for the `messy` family: did it actually ask?
    if case.must_ask and not result.questions:
        failures.append("expected the agent to ask a question; it did not")

    return CaseResult(
        case=case,
        passed=not failures,
        route=result.decision.route.value,
        failures=failures,
        run_id=result.run_id,
    )


def run_suite(family: str | None = None) -> dict:
    cases = [c for c in ALL_CASES if not family or c.family == family]
    results = [evaluate(c) for c in cases]

    families: dict[str, dict] = {}
    for r in results:
        bucket = families.setdefault(r.case.family, {"passed": 0, "total": 0})
        bucket["total"] += 1
        bucket["passed"] += int(r.passed)

    for bucket in families.values():
        bucket["score"] = round(bucket["passed"] / bucket["total"], 3)

    passed = sum(1 for r in results if r.passed)
    return {
        "results": results,
        "families": families,
        "passed": passed,
        "total": len(results),
        "score": round(passed / len(results), 3) if results else 0.0,
    }


def report(summary: dict) -> None:
    print(f"\n{BOLD}Eval suite{RESET}\n")
    current_family = None
    for r in summary["results"]:
        if r.case.family != current_family:
            current_family = r.case.family
            print(f"{BOLD}{current_family}{RESET}")
        mark = f"{GREEN}PASS{RESET}" if r.passed else f"{RED}FAIL{RESET}"
        print(f"  {mark}  {r.case.id:<34} {DIM}{r.route}{RESET}")
        for failure in r.failures:
            print(f"        {RED}\u2192 {failure}{RESET}")
        if not r.passed and r.case.note:
            print(f"        {DIM}{r.case.note}{RESET}")

    print(f"\n{BOLD}By family{RESET}")
    for name, stats in sorted(summary["families"].items()):
        color = GREEN if stats["score"] == 1.0 else (
            YELLOW if stats["score"] >= 0.8 else RED)
        print(f"  {name:<16} {color}{stats['passed']}/{stats['total']}"
              f"  ({stats['score']:.0%}){RESET}")

    overall = GREEN if summary["score"] == 1.0 else (
        YELLOW if summary["score"] >= 0.8 else RED)
    print(f"\n{BOLD}Overall{RESET} {overall}{summary['passed']}/{summary['total']}"
          f"  ({summary['score']:.0%}){RESET}\n")


def save_baseline(summary: dict) -> None:
    BASELINE_PATH.write_text(json.dumps({
        "score": summary["score"],
        "families": {k: v["score"] for k, v in summary["families"].items()},
    }, indent=2), encoding="utf-8")
    print(f"baseline written to {BASELINE_PATH}")


def check_baseline(summary: dict) -> int:
    if not BASELINE_PATH.exists():
        print(f"{YELLOW}no baseline recorded; run --baseline first{RESET}")
        return 0
    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    regressions = []
    for name, stats in summary["families"].items():
        floor = baseline["families"].get(name)
        if floor is not None and stats["score"] < floor:
            regressions.append(f"{name}: {stats['score']:.0%} < baseline {floor:.0%}")
    if regressions:
        print(f"\n{RED}{BOLD}REGRESSION{RESET}")
        for r in regressions:
            print(f"  {RED}{r}{RESET}")
        return 1
    print(f"{GREEN}no regressions against baseline{RESET}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--family")
    parser.add_argument("--baseline", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    summary = run_suite(args.family)

    if args.json:
        print(json.dumps({
            "score": summary["score"],
            "families": {k: v for k, v in summary["families"].items()},
            "failures": [
                {"id": r.case.id, "route": r.route, "failures": r.failures}
                for r in summary["results"] if not r.passed
            ],
        }, indent=2))
    else:
        report(summary)

    if args.baseline:
        save_baseline(summary)
        return 0
    if args.check:
        return check_baseline(summary)
    return 0 if summary["score"] == 1.0 else 1


if __name__ == "__main__":
    sys.exit(main())
