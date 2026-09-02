# Tasks — Full MVP

**Scope:** All 6 sprints, weeks 1–12, including Customer.io sync and rollout
**Format:** Working checklist — worked through directly, lives in repo
**Prereqs:** [`requirements.md`](./requirements.md) · [`roadmap.md`](./roadmap.md) · [`tech-stack.md`](./tech-stack.md)

**Legend:** 🚩 decision gate · ⛔ blocked on someone else · 🎯 milestone

> **Scope note:** "Full MVP" here includes Customer.io sync, which `requirements.md` §5 currently lists as out of v1. `requirements.md` should be updated to match, or the two docs will disagree in review.

---

## Sprint 0 — Setup
*Front-loaded into week 1. Small, but the access requests have lead time and block later sprints.*

### Access requests — file these on day one
- [ ] ⛔ Request read access to the email component/template library
- [ ] ⛔ Request export of last 12 months of email requests (tickets/Slack threads)
- [ ] ⛔ Request access to last 12 months of sent emails in Customer.io
- [ ] ⛔ Request brand + email copy guidelines in current form (deck, doc, wiki — whatever exists)
- [ ] ⛔ **Request Customer.io API credentials now** — not needed until Sprint 5, but procurement/security review is the long pole
- [ ] ⛔ Request Slack app creation permissions (needed Sprint 4)
- [ ] ⛔ Anthropic API key + billing account

### Repo scaffold
- [ ] `git init`, Python 3.11 venv, `pyproject.toml`
- [ ] Install: `anthropic`, `pydantic`, `jinja2`, `structlog`, `pytest`, `python-dotenv`
- [ ] Install Node + `mjml` CLI; verify compile works end to end
- [ ] Create folder structure per `tech-stack.md` §5:
  - [ ] `src/` `prompts/` `brand/` `components/` `briefs/` `evals/` `traces/`
- [ ] `.env.example` + `.gitignore` (secrets, traces, venv)
- [ ] `README.md` — how to run it, for future-me and my replacement
- [ ] Pre-commit hook: `black`, `ruff`

### Stakeholder groundwork
- [ ] 30-min intro with email team — frame as *reviewers and owners*, not recipients
- [ ] Identify 3–5 friendly stakeholders for the Sprint 4 pilot; get soft commitment now

---

## Sprint 1 — Ground truth and the brief contract
**Weeks 1–2**

### Library audit *(this determines whether the roadmap survives)*
- [ ] Inventory every component/template in the library; document what each does
- [ ] Sample 100 sent emails from the last 12 months
- [ ] Tag each: composable from existing library / needs new component / fully bespoke
- [ ] Calculate **library coverage %**
- [ ] 🚩 **Gate: if coverage <50%, stop.** Standardization is the real problem — rewrite Sprint 2 as library work and move the live date

### Request corpus
- [ ] Export and normalize ~100 past requests into `evals/fixtures/raw_requests/`
- [ ] Categorize by campaign type (nurture, launch, event, lifecycle, one-off)
- [ ] Categorize by audience/segment
- [ ] Tag recurring vs. one-off — quantifies how much volume needs *no* LLM judgment
- [ ] Identify the 5 messiest real requests; set aside as edge-case fixtures
- [ ] Document: what fields were missing most often, and how long each gap took to close

### Brief schema
- [ ] Draft `src/models/brief.py` — Pydantic v2 model
  - [ ] Required: campaign type, audience/segment, primary CTA, send window, offer/message
  - [ ] Optional: supporting copy, assets, links, personalization tokens, A/B variant
- [ ] Field-level validators (CTA present, URLs well-formed, send date in future)
- [ ] `is_complete()` + `missing_fields()` — **deterministic**, never model-decided
- [ ] Export JSON Schema to `briefs/schema.json` for non-Python readers
- [ ] Unit tests: valid, invalid, partial briefs

### Extraction
- [ ] `prompts/extract_brief.md` — free text → structured brief
- [ ] `src/steps/extract.py` — Claude Haiku via tool-use for structured output
- [ ] Retry + validation loop: reject malformed output, retry once, then escalate
- [ ] `prompts/clarify_gaps.md` — generate clarifying questions for missing fields
- [ ] `src/steps/clarify.py` — model phrases the question, code decides *which* fields need one

### Eval harness skeleton
- [ ] `evals/run.py` — replay fixtures, write results
- [ ] Hand-label 20 briefs as golden set (`evals/golden/briefs/`)
- [ ] Field-level accuracy scoring vs. golden
- [ ] Structured JSON trace per run → `traces/`
- [ ] `pytest` wired to run the eval suite

### Exit criteria
- [ ] 20 real requests parse into valid structured briefs
- [ ] Gap detection correct on held-out set of 10 incomplete briefs
- [ ] Library coverage % documented and shared
- [ ] Field accuracy baseline recorded

---

## Sprint 2 — Generation
**Weeks 3–4**

### Component library as code
- [ ] Convert each approved component to an MJML partial in `components/`
- [ ] `components/manifest.yaml` — for each: id, purpose, required data fields, when to use
- [ ] Jinja2 data binding into each partial
- [ ] `src/render/assemble.py` — component list + data → MJML → HTML
- [ ] Snapshot tests: each component renders without error
- [ ] Verify output in Gmail, Outlook, Apple Mail, and one mobile client

### Component selection
- [ ] `src/steps/select_components.py` — **rules first**: campaign type → component sequence
- [ ] Map the top 5 campaign types to deterministic sequences
- [ ] Model fallback only for briefs matching no rule
- [ ] `prompts/select_components.md` — constrained to manifest ids only
- [ ] Validate: every returned id exists in manifest, else escalate
- [ ] Log which path fired (rule vs. model) — expect rules to dominate

### Copy generation
- [ ] `prompts/generate_copy.md` — brief + brand voice + few-shot past emails
- [ ] Few-shot selection by metadata (campaign type, audience) — **not** embeddings, per `tech-stack.md` §4
- [ ] `src/steps/generate_copy.py` — Sonnet, structured output per component slot
- [ ] Hard constraint: no claims, offers, or dates not present in the brief
- [ ] Per-slot length constraints enforced in code, not prompt
- [ ] Subject line + preheader generation (3 options each)

### Pipeline
- [ ] `src/pipeline.py` — thin runner, explicit step contracts
- [ ] CLI: `python -m src.cli generate --brief path/to/brief.json`
- [ ] Full trace per run: inputs, prompts, raw responses, timings, token cost
- [ ] SQLite persistence: run id, brief, output, status

### Replay + validation
- [ ] Replay all 20 Sprint 1 briefs end to end
- [ ] Diff generated vs. the real email that shipped
- [ ] Blind review packet: 10 generated + 10 real, unlabeled, for email team
- [ ] 🚩 **Gate: email team blind-rates the output.** If they'd rebuild from scratch, stop and diagnose before layering a brand vet on bad output

### Exit criteria
- [ ] 20 briefs → 20 rendered emails, zero manual intervention
- [ ] Blind review completed and scored
- [ ] Cost per email measured

---

## Sprint 3 — Vetting, escalation, go live
**Weeks 5–6**

### Deterministic lint pass
- [ ] `brand/rules.yaml` — machine-readable, editable without Python
- [ ] `src/vet/lint.py`:
  - [ ] Subject line length bounds
  - [ ] Preheader present and length-bounded
  - [ ] CTA count within range
  - [ ] All images have alt text
  - [ ] All links well-formed + UTM parameters present
  - [ ] Banned/reserved terms absent
  - [ ] Required legal/footer blocks present
  - [ ] Placeholder text (`lorem`, `TODO`, `{{`) absent
- [ ] Each rule returns pass/fail + the specific offending element
- [ ] Unit test per rule, both directions

### Model-based voice check
- [ ] `brand/voice.md` — tone guidance in plain language
- [ ] `prompts/vet_voice.md` — rubric-scored, dimension by dimension
- [ ] `src/vet/voice.py` — Sonnet, returns score + reasoning per dimension
- [ ] Calibrate thresholds against 20 known-good past emails
- [ ] Require reasoning citing specific copy — no unsupported scores

### Escalation
- [ ] `src/escalate.py` — **deterministic routing** on lint results + voice scores + extraction confidence
- [ ] Rules: any lint fail → block; voice below threshold → flag; unresolved brief gaps → block; model fallback used for component selection → flag
- [ ] Escalation payload names the specific problem and the field responsible
- [ ] Never silently proceed — every escalation logged and surfaced
- [ ] Test: deliberately underspecified briefs must escalate, not improvise

### Eval suite
- [ ] Golden set: 20 briefs → expected components + pass/fail
- [ ] Messy inputs: 5 real worst-case requests from Sprint 1
- [ ] Adversarial: contradictory brief, empty brief, wrong-language brief, prompt-injection attempt in the request text
- [ ] Hallucination probes: brief with no offer — assert the agent asks rather than invents
- [ ] LLM-as-judge rubric for copy quality, human-spot-checked
- [ ] `make eval` — full suite, one command
- [ ] Record baseline scores; regressions fail CI

### Shadow mode → live
- [ ] Run agent in parallel on 5–10 real incoming requests
- [ ] Email team compares agent output vs. what they built
- [ ] Log every delta and categorize the cause
- [ ] Fix the top 3 recurring failure modes
- [ ] Select one low-risk real request for the first live send
- [ ] 🎯 **First live agent — real request, agent-generated, email-team reviewed, sent to a real list**

### Exit criteria
- [ ] One real email shipped through the agent
- [ ] Zero brand violations reached the email team across the shadow set
- [ ] Escalation fired correctly on every adversarial fixture

---

## Sprint 4 — Self-serve
**Weeks 7–8**

### Slack intake
- [ ] Create Slack app; scopes for the intake channel
- [ ] `src/slack/app.py` — Bolt for Python
- [ ] `/email-request` slash command + modal, and free-text channel trigger
- [ ] Thread-per-request: all interaction stays in one thread
- [ ] Post structured brief back for stakeholder confirmation

### Clarification loop
- [ ] Ask for missing fields in-thread, batched into one message
- [ ] Parse threaded replies back into the brief
- [ ] Re-validate; re-ask only what's still missing
- [ ] Timeout + nudge if the stakeholder goes quiet
- [ ] Target: gaps close in minutes, not days

### Preview
- [ ] Render preview to a hosted URL (signed, expiring)
- [ ] Post preview image + link in-thread
- [ ] Approve / request-changes buttons
- [ ] Free-text change requests → regenerate → new preview
- [ ] Version each iteration; keep history in the thread
- [ ] Cap iterations before escalating to a human

### Handoff
- [ ] On stakeholder approval, run brand vet
- [ ] Route to email team queue with brief, preview, vet results, and iteration history
- [ ] Email team accept / reject / edit, with reason captured

### Pilot
- [ ] Onboard 3–5 pilot stakeholders (15-min walkthrough each)
- [ ] Pinned example request in-channel as a template
- [ ] Instrument: request → approved preview time, iteration count, drop-off point
- [ ] Weekly feedback conversation with each pilot user

### Exit criteria
- [ ] 5 stakeholders file requests unassisted
- [ ] Median request → approved preview **under 48 hours**
- [ ] ≥1 documented revision caught at preview that would previously have surfaced post-build

---

## Sprint 5 — Customer.io sync
**Weeks 9–10**

- [ ] ⛔ Confirm API credentials landed (requested Sprint 0)
- [ ] `src/integrations/customerio.py` — thin adapter behind an interface
- [ ] Map internal email model → Customer.io campaign/draft payload
- [ ] Push approved email as **draft only** — no send capability in the code path, enforced structurally
- [ ] Preserve merge tags / personalization tokens through the sync
- [ ] Write back Customer.io draft id to SQLite; link it in the Slack thread
- [ ] Detect edits made in Customer.io post-sync; diff against source brief
- [ ] Feed those diffs into evals — they are the highest-signal quality data available
- [ ] Retry + idempotency (no duplicate drafts on retry)
- [ ] Failure path: sync fails → notify, fall back to manual handoff, never lose the artifact
- [ ] Integration tests against a sandbox/test workspace
- [ ] Email team QA walkthrough on 3 synced drafts

### Exit criteria
- [ ] Slack request → Customer.io draft with zero manual copy-paste
- [ ] Email team confirms drafts arrive QA-ready, not rebuild-ready
- [ ] No path exists in code from agent to send

---

## Sprint 6 — Scale and instrument
**Weeks 11–12**

### Rollout
- [ ] Open intake to full stakeholder population
- [ ] Announce in marketing all-hands + channel
- [ ] Docs: how to file a good request, what the agent can and can't do, what to expect
- [ ] Two office-hours sessions in week 11
- [ ] Publish 3 real before/after examples with actual turnaround times
- [ ] Named backup owner on the email team; walk them through runbook + `README`

### Instrumentation
- [ ] Dashboard against `requirements.md` §6:
  - [ ] SLA: request → ready for QA
  - [ ] Requests through new path vs. old path
  - [ ] Revision rounds per email
  - [ ] First-pass acceptance rate
  - [ ] Brand violations reaching the email team
  - [ ] Email team hands-on minutes per email
  - [ ] Sends per month (throughput)
  - [ ] Tests shipped per month (velocity)
- [ ] Baseline the pre-launch numbers from the Sprint 1 corpus — **do this before the numbers move**
- [ ] Weekly automated report to the channel
- [ ] Repeat-usage tracking: stakeholders returning for a 2nd and 3rd email
- [ ] Track old-path volume — the real trust signal is Slack DMs to the email team going quiet

### Hardening
- [ ] Runbook: common failures and fixes
- [ ] Alerting on pipeline failure and escalation-rate spikes
- [ ] Cost monitoring + per-email budget alert
- [ ] Prompt/rule change process documented — PR + eval suite must pass
- [ ] Post-MVP backlog from pilot feedback

### Exit criteria
- [ ] ≥30% of eligible requests through the new path
- [ ] Real measured before/after on SLA and sends per month
- [ ] Someone other than me has run the pipeline successfully

---

## Cross-cutting — every sprint
- [ ] Eval suite green before any merge
- [ ] Prompts and brand rules changed only via PR
- [ ] Traces retained for every production run
- [ ] Weekly 15-min email team check-in
- [ ] Update this file — mark done, log what changed and why

---

## Critical path
Blocking dependencies, in order. Everything else can slip without moving the live date.

1. Library access → library audit → **Sprint 1 gate**
2. Component library encoded → generation
3. Generation quality → **Sprint 2 gate**
4. Brand vet + escalation → 🎯 first live agent
5. Slack app approval → self-serve
6. Customer.io credentials → sync *(requested Sprint 0 for exactly this reason)*
