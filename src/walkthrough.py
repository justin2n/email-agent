"""
What a marketer actually sees.

The CLI is an engineering surface. This renders the same pipeline as the Slack
thread a marketer would experience — the real `ThreadState` machine from
`src/slack/app.py`, driven by scripted replies instead of a live workspace.

Nothing here is mocked. `handle_new_request`, `handle_answers` and
`handle_change_request` are the exact functions the Slack app calls; only the
transport is simulated. That is deliberate: the conversation logic is pure, so
it can be demonstrated and unit-tested without a Slack token.

    python3 -m src.walkthrough
"""

from __future__ import annotations

import textwrap
import time

from .slack.app import (
    ThreadState,
    handle_answers,
    handle_change_request,
    handle_new_request,
)

BOLD, DIM, RESET = "\033[1m", "\033[2m", "\033[0m"
GREEN, PURPLE = "\033[32m", "\033[35m"

WIDTH = 68
PAUSE = 0.0   # set to 0.9 to play it back at conversation speed

CHANNEL = "#marketing-email-requests"


def _rule() -> None:
    print(f"{DIM}{'-' * WIDTH}{RESET}")


def _clock(stamp: str) -> None:
    _rule()
    print(f"{DIM}{stamp}{RESET}")


def _human(who: str, text: str) -> None:
    print(f"\n{BOLD}{who}{RESET} {DIM}- {CHANNEL}{RESET}")
    for line in textwrap.wrap(text.strip(), WIDTH - 4) or [""]:
        print(f"  {line}")
    time.sleep(PAUSE)


def _agent(blocks: dict) -> None:
    print(f"\n{PURPLE}{BOLD}Email Agent{RESET} {DIM}APP{RESET}")
    for block in blocks.get("blocks", []):
        kind = block["type"]
        if kind == "section":
            for line in block["text"]["text"].split("\n"):
                clean = line.replace("*", "").replace("_", "")
                for wrapped in textwrap.wrap(clean, WIDTH - 4) or [""]:
                    print(f"  {wrapped}")
        elif kind == "context":
            for element in block["elements"]:
                print(f"  {DIM}{element['text']}{RESET}")
        elif kind == "actions":
            buttons = "   ".join(f"[ {e['text']['text']} ]" for e in block["elements"])
            print(f"  {GREEN}{buttons}{RESET}")
    time.sleep(PAUSE)


def _aside(text: str) -> None:
    print()
    for line in textwrap.wrap(text, WIDTH - 6):
        print(f"  {DIM}-> {line}{RESET}" if line == textwrap.wrap(text, WIDTH - 6)[0]
              else f"     {DIM}{line}{RESET}")


def main() -> int:
    print(f"\n{BOLD}What a marketer sees{RESET}")
    print(f"{DIM}The same pipeline as `make demo`, in the surface "
          f"they'd actually use.{RESET}\n")

    # ------------------------------------------------------------------
    # 9:14 — a PMM fires off a request between meetings.
    # ------------------------------------------------------------------
    _clock("Monday, 9:14am")

    request = ("@Email Agent can we get something out about Dev Mode Inspect? "
               "For developers. Needs to go Tuesday.")
    _human("Priya Raman", request)

    state = ThreadState(
        thread_ts="1730000000.001",
        channel="C-EMAIL-REQUESTS",
        requester="Priya Raman",
        raw_request=request,
    )
    state, blocks = handle_new_request(state)
    _agent(blocks)

    _aside("Under a minute to find out what's missing. On the old path that "
           "took two days of Slack tag before anyone knew.")

    # ------------------------------------------------------------------
    # 9:20 — she answers in prose, in the thread.
    # ------------------------------------------------------------------
    _clock("Monday, 9:20am")

    reply = ("product launch\n"
             "Developers can pull production-ready specs straight from a Figma "
             "file without waiting on a designer\n"
             "Open Dev Mode\n"
             "https://www.figma.com/dev-mode")
    _human("Priya Raman", reply.replace("\n", "   /   "))

    state, blocks = handle_answers(state, reply)
    _agent(blocks)

    _aside("She wrote 'product launch', not 'product_launch', and answered a "
           "question that wasn't asked. Both handled. And it won't pad a "
           "three-point layout with invented copy - it asks.")

    # ------------------------------------------------------------------
    # 9:23 — she supplies the three points.
    # ------------------------------------------------------------------
    _clock("Monday, 9:23am")

    points = ("Copy CSS, iOS and Android values from any layer\n"
              "See exactly what changed between versions\n"
              "Works in the free tier for every developer seat")
    _human("Priya Raman", points.replace("\n", "   /   "))

    # Supporting points aren't a single schema field, so they go back through
    # the request the same way she'd have written them the first time.
    state.raw_request = state.raw_request + "\n- " + points.replace("\n", "\n- ")
    state, blocks = handle_answers(state, "")
    _agent(blocks)

    # ------------------------------------------------------------------
    # 9:26 — she reacts to a real email, not a brief.
    # ------------------------------------------------------------------
    _clock("Monday, 9:26am")
    print(f"\n  {DIM}She opens the preview and reads the actual email.{RESET}")
    print(f"  {DIM}This is the gate that removes the rework: people can't{RESET}")
    print(f"  {DIM}react to a brief, only to a finished email.{RESET}")

    _human("Priya Raman", "Close. Can we lead on the free tier? That's the part "
                          "developers actually care about.")

    state, blocks = handle_change_request(
        state, "Lead on the fact it works in the free tier for every developer seat")
    _agent(blocks)

    _human("Priya Raman", "[ Looks good ]")

    # ------------------------------------------------------------------
    _rule()
    print(f"""
{BOLD}Then it reaches the email team{RESET}

  They get the brief, the rendered email, every flag the checks raised,
  and the full iteration history - not a half-formed request.

  Their job is review, not production. They approve, edit or reject, and
  their edits become the data that improves the system.

{BOLD}What Priya did{RESET}
  Three messages. Four questions answered. One preview read.
  Twelve minutes of her attention, not two weeks of calendar time.

{BOLD}What she never did{RESET}
  Fill in a form. Learn a tool. Write a brief in a template.
  Chase anyone. Sit in a queue to find out something was missing.
""")
    _rule()
    print(f"{DIM}Same pipeline as `make demo`. Different surface.{RESET}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
