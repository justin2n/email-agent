# Email production agent

Turns a marketing colleague's informal request into a brand-checked email draft,
with a human approving at two points and nothing invented along the way.

Proof-of-concept for the email production opportunity — see [`../evaluation.md`](../evaluation.md)
for why this one was picked first, and [`../requirements.md`](../requirements.md) for the case.

---

## Run it

No API key, no network, no install beyond two libraries. Runs on Python 3.9+,
including the version macOS ships:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install jinja2 pyyaml
make app
```

That opens a browser at `localhost:8000` with the **whole lifecycle** across
four tabs:

| Tab | Sprint | What you do |
|---|---|---|
| **Request** | 4 | File a request, answer the gaps, preview, iterate, approve |
| **Email team** | 3 | Review the queue, accept / edit / reject |
| **Customer.io** | 5 | Push a draft, inspect the exact payload |
| **Metrics** | 6 | Throughput, first-pass acceptance, rule-vs-model ratio |

It runs on Python's stdlib `http.server` — no Flask, no npm, no build step —
because a demo that needs an install is a demo that doesn't happen.

**Suggested demo path:** *Vague ask* → watch it ask instead of guess → answer →
give it three points → preview → request a change → approve → switch to
**Email team**, accept with edits → **Customer.io**, push the draft → **Metrics**.
Then come back and run *Invented facts* to show it blocking fabricated figures.

**For real copy quality**, add a key:

```bash
python3 -m pip install anthropic
export ANTHROPIC_API_KEY=sk-...
export LLM_BACKEND=anthropic
make app
```

The header shows which engine is live. Everything else is identical — that seam
is the architecture, not a testing convenience.

Prefer the terminal? `make demo` runs four scenarios there.

No `make`? Call the modules directly: `python3 -m src.cli demo`,
`python3 -m unittest discover tests`, `python3 evals/run.py`.

That runs four scenarios in order:

| | Scenario | What it shows |
|---|---|---|
| 1 | Happy path | Rules pick the components. The model is never asked. |
| 2 | Incomplete brief | It **asks** instead of inventing. |
| 3 | Brand violation | Banned terms and a forbidden CTA label, caught and named. |
| 4 | Invented facts | Fabricated statistics blocked before a human sees them. |

### Three surfaces, one pipeline

| Command | Surface | For |
|---|---|---|
| `make app` | Browser UI | Showing it to anyone |
| `make walkthrough` | Simulated Slack thread | The real marketer flow |
| `make demo` | Terminal | Engineering detail |

The browser UI is a demo surface, not the product. The real front door is
Slack (`src/slack/app.py`, Sprint 4).

**See it as a marketer would:**

```bash
make walkthrough
```

The CLI is an engineering surface — no marketer types `python -m src.cli`.
This renders the same pipeline as the Slack thread they'd actually use, driving
the real `ThreadState` machine from `src/slack/app.py` with scripted replies
instead of a live workspace. Only the transport is simulated.

```bash
make test     # 57 unit tests, deterministic layer
make eval     # 15 eval cases across 4 families
make check    # what CI runs
```

Single request:

```bash
python -m src.cli generate --request "Launching Dev Mode for developers Tuesday.
Button 'Open Dev Mode' -> https://www.figma.com/dev-mode" --save
```

## Going live

```bash
pip install anthropic
export ANTHROPIC_API_KEY=sk-...
python -m src.cli generate --backend anthropic --request "..."
```

Nothing else changes. That's the point — see below.

---

## The design in one table

| Step | Owner | Why |
|---|---|---|
| Read a messy request | **Model** | Genuine language understanding |
| Decide the brief is incomplete | **Code** | A schema check, not a judgment call |
| Phrase the follow-up question | **Model** | Wording is judgment |
| Pick components | **Rules**, model only as fallback | Most campaigns are a lookup someone never wrote down |
| Write copy | **Model** | The one thing that genuinely needs it |
| Build the HTML | **Code** | Jinja2 only |
| Brand checks | **Code** | Right 100% of the time, costs nothing |
| Judge tone | **Model** | Irreducibly judgment |
| **Decide whether to escalate** | **Code** | A model that decides when to ask for help can decide not to |

Two constraints do most of the work:

**The model never emits HTML.** It picks component ids from a closed vocabulary and
writes copy into named slots. Code assembles. That removes the entire class of
"the model produced a broken or off-brand layout" failures — structurally, not by
asking nicely.

**The model never decides whether an email ships.** It contributes evidence — a
confidence value, a tone score. `src/escalate.py` applies thresholds that live in
version control and can be tested with no model in the loop.

### The seam that proves it

Every model call goes through `src/llm/client.py` and returns structured data
against a known schema. Swap `AnthropicClient` for `StubClient` and the entire
pipeline — selection, assembly, linting, grounding, escalation — runs unchanged
and every test still passes.

That isn't a testing convenience bolted on afterwards. If swapping the model out
broke the pipeline, too much of the logic would be living inside the prompt.

---

## Layout

```
prompts/          One .md per step. Reviewed in PRs by people who don't write Python.
brand/
  rules.yaml      Deterministic lint rules — lengths, banned terms, UTM, alt text
  voice.md        Tone guidance, the only brand input needing judgment
components/
  manifest.yaml   The closed vocabulary + campaign-type → component sequences
  partials/       Email-safe HTML, compiled from MJML
briefs/           JSON Schema for the brief contract
src/
  models/brief.py       The contract. Completeness decided here, in code.
  llm/                  Adapter + offline stub
  steps/                intake · select · generate
  render/assemble.py    Jinja2 → email-safe HTML
  vet/                  lint (rules) · grounding (rules) · voice (model)
  escalate.py           The router. Deterministic.
  pipeline.py           ~150 lines of sequencing, no framework
  integrations/         Customer.io adapter — drafts only, no send path
  slack/                Self-serve intake
evals/                  Cases, runner, baseline
traces/                 One JSON per run
```

### What a marketer can change without an engineer

Everything in `prompts/`, `brand/` and `components/`. Adding a campaign type is a
YAML entry. Changing the banned-terms list is one line. CI re-runs the eval suite
on every such change, so the guardrail on that freedom is automated rather than
a person.

---

## Reliability

**Grounding.** Every figure and proper noun in the finished email is checked
against what the requester actually supplied. Unsupported figures block;
unsupported names flag. Tuned to over-flag: a false positive costs ten seconds,
a false negative puts an invented product claim in a customer's inbox.

**Closed vocabulary.** A component id outside the manifest raises. It is never
silently dropped — that would produce a quietly wrong email.

**No silent fallback.** Each model step retries once, then escalates. There is no
best-effort path.

**Failed checks aren't passes.** If the tone check can't run, the email routes to
review rather than through.

**Escalations name the rule.** Every one carries the specific rule and evidence.
A reviewer never has to work out what went wrong — which is what makes them
willing to trust it.

### Routes

| Route | Meaning |
|---|---|
| `proceed` | Clean. Straight to email team QA. |
| `flag_for_review` | Proceeds, human is warned, with specifics. |
| `back_to_requester` | The brief can't support an email yet. |
| `block` | Stops. Brand violation or invented content. |

---

## Observability

Every run writes a full JSON trace to `traces/` — inputs, prompt fingerprints,
each step's output, timings, tokens, and the decision with reasons. Runs persist
to SQLite (`email_agent.db`), one file, no server.

```bash
python -m src.cli metrics
```

Returns run counts by route, the rule-vs-model selection ratio, first-pass
acceptance, and average duration — the dashboard from `requirements.md` §6.

**The rule/model ratio is the one to watch.** If the model fallback starts firing
often, the fix is to add a sequence to the manifest, not to improve the prompt.

---

## Human in the loop

```
requester  →  agent asks about gaps        (minutes, not days)
           →  requester answers in-thread
           →  rendered preview            ← GATE 1, absorbs the rework
           →  approve / request changes
           →  email team QA               ← GATE 2, never removed in v1
           →  Customer.io draft
```

Gate 1 is where the hours are. Per `requirements.md` §2, most of the two-week SLA
is latency and rework, not build time — stakeholders can't react to a brief, only
to a finished email.

Gate 2 stays because adoption depends on the email team trusting this, and you
earn that by leaving them in control.

### The free eval data

`src/integrations/customerio.py:diff_against_source()` compares the draft the
email team edited against what the agent produced. Every edit is a labelled
record of exactly where it was wrong — generated at no extra cost by work they
were already doing. Those diffs feed the eval suite.

---

## Known limits

- **`StubClient` is not a language model.** It's a rule-based fixture generator,
  good enough to exercise real branching offline. Copy quality is only meaningful
  with `--backend anthropic`.
- **The component library is invented.** Realistic, but not Figma's actual one.
  Sprint 1 in `../tasks.md` exists to audit the real library, and if it covers
  under ~50% of past emails the roadmap changes.
- **Grounding is lexical, not semantic.** It catches invented figures and names.
  It would not catch a plausible-sounding but wrong paraphrase of a real claim —
  which is part of why Gate 2 stays.
- **No deliverability testing.** Litmus-style client rendering stays a human step.
- **English only.** Non-English requests are out of scope for v1 and escalate.
