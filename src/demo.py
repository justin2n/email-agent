"""
The four demo scenarios, in presentation order.

  1. Happy path        a normal request, straight through
  2. Incomplete brief  it asks instead of inventing
  3. Brand violation   the linter catches it and names the rule
  4. Hallucination     an invented figure is caught and blocked

Scenario 2 is the one that earns trust in the room. Scenario 4 is the one
that answers "but what if it makes something up".

    python -m src.cli demo
"""

from __future__ import annotations

import textwrap

from .escalate import Route
from .llm.client import StubClient, get_client
from .pipeline import run

BOLD, DIM, GREEN, YELLOW, RED, BLUE, RESET = (
    "\033[1m", "\033[2m", "\033[32m", "\033[33m", "\033[31m", "\033[36m", "\033[0m"
)
ARROW = " \u203a "

HAPPY = """
We're launching Dev Mode Inspect for the developer audience next Tuesday.
Main thing: developers can now pull production-ready specs straight from a
Figma file without a designer handing anything over.
- Copy CSS, iOS and Android values from any layer
- See exactly what changed between versions
- Works in the free tier for every developer seat
Button should say "Open Dev Mode" and go to
https://www.figma.com/dev-mode
Needs to go out Tuesday.
"""

INCOMPLETE = """
Hey - can we get an email out about the new thing? Designers would care about it.
Thanks!
"""

BRAND_VIOLATION = """
Webinar invite for design leaders. It's a revolutionary session on scaling
design systems - genuinely game-changing stuff.
Event: Scaling Design Systems, 2026-11-18, 11am PT, 45 minutes, online.
Button: "Learn more" -> https://www.figma.com/events/scaling-design-systems
Send it this week.
"""

HALLUCINATION = """
Product launch email to designers about the new auto-layout improvements.
Ship it next week. Button "Try auto layout" -> https://www.figma.com/auto-layout
"""

# Forces the copy step to invent a statistic that appears nowhere in the brief.
HALLUCINATION_FIXTURE = {
    "generate_copy": {
        "slots": {
            "headline": "Auto layout, rebuilt from the ground up",
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

SCENARIOS = [
    ("1. Happy path", HAPPY,
     "A complete request. Rules pick the components, no model needed for selection.",
     None),
    ("2. Incomplete brief", INCOMPLETE,
     "It asks rather than inventing. This is the behaviour that earns trust.",
     None),
    ("3. Brand violation", BRAND_VIOLATION,
     "Banned terms and a forbidden CTA label. Caught by rules, named precisely.",
     None),
    ("4. Invented facts", HALLUCINATION,
     "Copy contains figures found nowhere in the brief. Blocked before a human sees it.",
     HALLUCINATION_FIXTURE),
]


def run_demo() -> int:
    print(f"\n{BOLD}Email production agent \u2014 demo{RESET}")
    print(f"{DIM}Four scenarios. Watch the route on each one.{RESET}\n")

    for title, request, note, fixture in SCENARIOS:
        print("\u2500" * 74)
        print(f"{BOLD}{title}{RESET}")
        print(f"{DIM}{note}{RESET}\n")
        print(f"{DIM}Request:{RESET}")
        for line in textwrap.dedent(request).strip().splitlines()[:6]:
            print(f"{DIM}  \u2502 {line}{RESET}")
        print()

        client = StubClient(fixture) if fixture else get_client()
        result = run(request, client=client, requester="demo", source="demo")

        color = {Route.PROCEED: GREEN, Route.REVIEW: YELLOW,
                 Route.REQUESTER: BLUE, Route.BLOCK: RED}[result.decision.route]
        print(f"  {color}\u25cf {result.decision.route.value.upper().replace('_', ' ')}{RESET}"
              f"  {DIM}({result.trace.duration_ms}ms){RESET}")

        if result.selection:
            marker = "rule" if result.selection.path == "rule" else "MODEL FALLBACK"
            chain = ARROW.join(result.selection.components)
            print(f"  {DIM}components ({marker}):{RESET} {chain}")
        if result.subject:
            print(f"  {DIM}subject:{RESET} {result.subject}")

        if result.questions:
            print(f"\n  {BLUE}It asked:{RESET}")
            for q in result.questions:
                print("    \u2022 " + q)

        if result.decision.reasons:
            print(f"\n  {DIM}Reasons:{RESET}")
            print(result.decision.explain())
        print()

    print("\u2500" * 74)
    print(f"{DIM}Traces written to traces/. Run `python -m src.cli metrics` "
          f"for the dashboard.{RESET}\n")
    return 0
