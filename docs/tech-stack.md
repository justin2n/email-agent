# Tech Stack

**Build posture:** Code-first — Python primary, Node where required, runs locally
**Team:** Solo, no dedicated engineering support
**Prereqs:** [`evaluation.md`](./evaluation.md) · [`requirements.md`](./requirements.md)

---

## 1. The constraint that decides everything

**One person builds this, and the same person maintains it.**

That single fact does more to determine the stack than any technical preference. Every dependency is something I get paged for alone. Every clever abstraction is something only I can debug. Every self-hosted service is an on-call rotation of one.

So three principles govern every choice below:

1. **Boring beats clever.** Prefer the technology with the largest population of people who could take this over from me.
2. **Fewer moving parts, even at the cost of features.** A capability that adds a service to maintain has to be worth an ongoing tax, not just a one-time build.
3. **Escape hatches over frameworks.** Frameworks are load-bearing until they aren't. Where an abstraction would hide the LLM call, I want the LLM call.

A corollary worth stating plainly: **this stack should be deliberately unremarkable.** A marketing-ops build that requires a bespoke toolchain to run is a build that dies when its author changes teams.

---

## 2. The stack

| Layer | Choice | Why |
|---|---|---|
| Language | **Python 3.11+** | Best LLM ecosystem, widest hireability, one language for pipeline + evals |
| Model API | **Anthropic API** — Sonnet for generation, Haiku for classification | Tool-use gives reliable structured output; Haiku makes cheap steps genuinely cheap |
| Schema & validation | **Pydantic v2** | The brief contract lives in code, not in a prompt. See §3. |
| Email rendering | **MJML** → responsive HTML | Solves the Outlook problem, which is the actual hard part of email HTML |
| Templating | **Jinja2** over MJML partials | Data binding into approved components |
| Orchestration | **Plain Python functions + thin pipeline runner** | See §4 — this is the most contested choice |
| Persistence | **SQLite** + versioned artifacts on disk | Zero ops. Single file. Backs up with `cp`. |
| Intake surface | **Slack Bolt for Python** (Sprint 4) | Stakeholders already live there; a new form is a new thing to ignore |
| Evals | **pytest** + golden files + LLM-as-judge rubrics | Runs in CI, runs locally, no new service |
| Observability | **structlog** + full JSON trace per run | Every run reconstructible from disk |
| Prompts | Versioned `.md` / `.j2` files in repo | Not inline strings. See §5. |
| Secrets | `.env` locally → platform secrets in deploy | Standard |

**On Node:** MJML is a Node package, so this is Python-primary with a Node dependency for the compile step. I'd rather own that small polyglot seam than hand-roll email-client-safe HTML in pure Python — table-based layout for Outlook is a well-known tarpit and MJML is the ecosystem's answer to it.

---

## 3. Where deterministic logic ends and the model begins

The stack encodes a specific position: **the model does judgment, code does everything else.** This is a stack decision, not just an architecture one, because it determines what needs a model at all.

| Step | Owner | Why |
|---|---|---|
| Brief field validation, required-field checks | **Pydantic** | Deterministic, testable, free, never wrong |
| Extracting a brief from free text | **Claude (Haiku)** | Genuine language understanding |
| Deciding a brief is incomplete | **Pydantic** | It's a schema check, not a judgment call |
| Deciding *what to ask* about a gap | **Claude (Haiku)** | Phrasing a good clarifying question |
| Copy generation to a brief | **Claude (Sonnet)** | Genuine judgment |
| Component selection | **Code (rules) + Claude fallback** | Most cases are deterministic mappings; only novel briefs need judgment |
| Assembling HTML | **Jinja2 + MJML** | Never the model. Composition from approved blocks only. |
| Brand rule checks (subject length, CTA count, alt text, link validity, banned terms) | **Code — lint pass** | 100% reliable, instant, zero cost |
| Brand *voice* and tone assessment | **Claude (Sonnet), rubric-scored** | Irreducibly judgment |
| Escalation routing | **Code, on model confidence + lint results** | The decision to escalate must itself be deterministic |

The load-bearing line: **the model never emits HTML.** It selects components and writes copy; code assembles. That single constraint eliminates the entire class of "the LLM hallucinated a broken template" failures, and it's why a small, finite component library matters more to this build than model quality does.

---

## 4. Rejected alternatives

The rejections say more than the selections.

**LangChain / LlamaIndex / CrewAI — rejected.**
The abstraction cost exceeds the benefit at this scale. This pipeline is roughly six steps with clear contracts between them; that's a few hundred lines of plain Python. Frameworks obscure the prompt and the token flow exactly when I need to see them for eval work, and they add a fast-moving dependency to a system with a maintainer count of one. If the pipeline grows past ~15 steps with real branching, revisit.

**Vector database / RAG — rejected for v1.**
The temptation is to embed 600 past emails and retrieve similar ones. But the retrieval target here is small, finite, and *structured* — a component library and a set of brand rules. Both fit in context. A vector DB would add a service, an embedding pipeline, and a whole new failure mode to solve a problem I don't have yet. Direct context injection plus few-shot examples selected by metadata (campaign type, audience) gets the same result with zero infrastructure. Revisit if the past-email corpus becomes genuinely useful for style-matching at scale.

**Fine-tuning — rejected.**
Wrong tool for a 600-example corpus, and it bakes brand guidelines into weights I can't diff, review, or roll back. Guidelines change; prompts and rule files should change with them in a pull request.

**A dedicated LLMOps platform (LangSmith, Braintrust, W&B) — deferred, not rejected.**
Genuinely useful, and I'd want one eventually. But structured JSON traces on disk cover the solo debugging case at zero setup cost, and pytest covers evals. Adopt when there's more than one person who needs to read the traces.

**No-code (Gumloop, n8n, Zapier) — rejected here, but with a real tradeoff.**
Faster to a first demo, and genuinely better for handoff to non-technical owners. Rejected because the assignment weights modularity, version control, and eval rigor — and prompts-in-a-canvas can't be code-reviewed, diffed, or unit-tested. That's the whole substance of the repo and evaluation sections. The honest cost of this choice: a marketer cannot modify this build without me. Section 5 of the repo plan mitigates that by pushing everything a marketer would want to change — prompts, brand rules, component definitions — into flat files they can edit without touching Python.

**Postgres for v1 — rejected.**
SQLite until there's concurrent write pressure. It's one file, it's transactional, and migrating later is a solved problem.

---

## 5. What lives in files, not code

Because a marketer should be able to change the system's behavior without a Python review:

```
prompts/          .md files, one per step, versioned
brand/            rules.yaml — lint rules, banned terms, thresholds
                  voice.md — tone guidance passed to the model
components/       .mjml partials + components.yaml manifest
briefs/           JSON schema (generated from Pydantic, human-readable)
evals/            golden briefs + expected outputs
```

Everything above is reviewable in a pull request by someone who doesn't write Python. Everything in `src/` is plumbing that shouldn't need to change when the brand voice does.

---

## 6. Deployment path

**v1 (Sprints 1–3):** runs locally. CLI in, HTML file out. No deployment at all — this is the right answer for a proof-of-concept and I'd resist pressure to host it early.

**v2 (Sprint 4+):** single container, one platform service. Cloud Run or Fly.io on the merits — but the real selection criterion is **whatever Figma already runs**, because the failure mode I most want to avoid is being the only person who can deploy it.

**Never in v1:** Kubernetes, a queue, a worker pool, autoscaling. Peak load is ~60 requests/month. That's two per day. A single process handles it with room to spare, and pretending otherwise is how solo projects die.
