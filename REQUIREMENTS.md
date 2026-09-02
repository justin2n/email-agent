# Requirements — Self-Serve Email Production

**Status:** Draft for review
**Prereq:** [`evaluation.md`](./evaluation.md) — email production scored **4.75 / 5**, first of four opportunities
**Scope:** v1 — intake → structured brief → generation → stakeholder preview → brand vet. Customer.io sync deferred to v2.

---

## 1. Why this one

From `evaluation.md`, email won on three axes at once — hours, feasibility, and eval-ability — and on a fourth that matters more than its 5% weight suggests: it is the **substrate for the other three opportunities**. The brief schema, brand-adherence vetting, stakeholder preview loop, and human-in-the-loop gate built here are ~60% of what ABM landing pages and localization need. Building email first means the next two builds are integrations, not rebuilds.

The reason email is tractable at all is that it's the most *constrained* medium in marketing: fixed width, modular blocks, a finite component library, a destination with an API. Constraint is what makes it automatable.

---

## 2. The business problem

### Current state

A marketing email today takes **two weeks** and passes through at least four handoffs:

| Stage | What happens | Where time goes |
|---|---|---|
| Intake | Stakeholder files a request | Brief arrives incomplete — missing audience, CTA, offer, or send date |
| Clarification | Email team chases the gaps | Async Slack/ticket round trips, often 2–3 days of latency for 20 minutes of work |
| Build | Email team builds in Customer.io | ~2 hrs of hands-on production |
| Revision | Stakeholder reacts to the built email | Multiple rounds; changes that could have been caught at brief stage now cost a rebuild |

### The three real problems underneath

**1. The brief is the bottleneck, not the build.**
Two hours of build time cannot explain a two-week SLA. The gap is *latency* — waiting on answers, waiting in queue, waiting for a reaction. Most of the elapsed time is nobody working.

**2. Stakeholders can't react to a brief; they can only react to an email.**
This is the structural cause of the revision rounds. A stakeholder approves a brief they haven't visualized, then changes their mind when they see it rendered. Every one of those changes is discovered *after* the expensive step.

**3. The SLA is a throughput cap, and the cap sets strategy.**
When email takes two weeks, teams stop proposing tests. Campaigns get scoped to what the queue can absorb rather than what the funnel needs. The cost isn't only the emails that ship late — it's the ones never requested.

### Volume

- **40–60 requests/month** (~600/year)
- **2 hrs** build per email, plus multiple revision rounds
- **2-week SLA**, effectively a hard ceiling on campaign and test velocity

---

## 3. Audience

Three distinct users with genuinely conflicting incentives. The design has to serve all three or it gets rejected by one of them.

### Requesting stakeholders — *primary user*
PMMs, lifecycle marketers, campaign managers, regional marketing. Non-technical. Dozens of people across the org.

- **Want:** their email live, this week, without learning a new tool
- **Fear:** a system that makes them do more work upfront for the same wait
- **Success looks like:** they describe what they want in plain language and see a rendered email in minutes

### Email team — *primary reviewer and owner*
Small team (est. 2–4). Owns brand, quality, deliverability, and Customer.io.

- **Want:** fewer half-formed requests, less mechanical build work, retained control over what ships
- **Fear:** an agent that floods them with plausible-looking garbage to fix, or that ships something off-brand under their name — this is the failure mode that kills adoption
- **Success looks like:** requests arrive complete and pre-vetted; their job shifts from production to judgment

### Marketing leadership — *sponsor*
- **Want:** more campaigns, more tests, faster response to market moments
- **Success looks like:** send volume and test velocity up, SLA down, no increase in brand incidents

> **Design implication:** the email team must never lose the final gate in v1. Adoption depends on them trusting the system, and trust is earned by the agent escalating well — not by it being autonomous.

---

## 4. ROI

Modeled at the **upside case** — what this is worth if it works as intended and gets adopted. Assumptions are stated explicitly so each can be swapped for actuals. Two inputs are placeholders and marked as such.

### 4a. Hours saved

**Baseline — current annual effort**

| Activity | Per email | Annual (600 emails) |
|---|---|---|
| Build | 2.0 hrs | 1,200 hrs |
| Stakeholder revision rounds (est. 3 × 30 min, both sides) | 1.5 hrs | 900 hrs |
| Intake clarification and queue management | 0.5 hrs | 300 hrs |
| **Total** | **4.0 hrs** | **2,400 hrs** |

**Upside case — 70% reduction**

Generation removes most of the build. Structured intake removes most of the clarification. Preview-before-build removes most of the revision rounds — the highest-leverage of the three, because it eliminates rework rather than accelerating it.

| | Annual |
|---|---|
| Hours saved | **~1,680 hrs** |
| FTE equivalent | **~0.8 FTE** returned to the email team |
| Loaded cost avoided @ $85/hr blended | **~$143K/yr** |

The dollar figure is the least interesting number here. The real result is that ~0.8 FTE of specialist capacity moves from mechanical production to strategy, QA, and deliverability — work only that team can do.

### 4b. Revenue driven

Three levers, in descending order of confidence.

> ⚠️ **Placeholder input.** Modeled against an assumed **$20M/yr email-influenced pipeline**. This is a stand-in and must be replaced with actuals before the number is quoted anywhere. The *structure* of the model holds regardless of the input.

**Lever 1 — Send volume.** Removing the production ceiling lets the calendar be set by strategy rather than queue depth. Upside: send volume roughly doubles. Pipeline impact is sub-linear (audience fatigue, diminishing returns), modeled at **+25% → $5.0M**.

**Lever 2 — Test velocity.** This is the largest and slowest-compounding lever. At a 2-week SLA, A/B testing is effectively unaffordable — each test costs a campaign slot. At a 48-hour SLA it becomes routine. Going from a handful of tests/year to 50+ compounds subject line, offer, and layout learnings across every subsequent send. Modeled at **+15% blended conversion → $3.0M**.

**Lever 3 — Timeliness.** Emails that ship at the launch moment rather than after it. Hard to isolate, real in practice. Not separately modeled — treated as upside inside Levers 1 and 2.

**Combined, discounted 30% for overlap between levers:**

| | Upside case |
|---|---|
| Incremental email-influenced pipeline | **~$5.6M** |
| Bookings @ assumed 25% close rate | **~$1.4M** |
| Plus cost avoidance | ~$143K |

### 4c. The honest caveat

Carried forward from `evaluation.md`: **the attribution chain has a soft link.** "Faster SLA → more sends → more pipeline" is directionally sound but not cleanly attributable, and the volume lever is genuinely sub-linear.

The mitigation is not to pretend otherwise. Instrument the **leading indicators** the build controls directly — SLA, throughput, test count, first-pass acceptance rate — hold a real before/after on sends-per-month, and treat channel revenue as *influenced*, never sourced. A build that claims credit for the whole channel loses credibility the first time someone audits it.

---

## 5. Scope

### In scope — v1

**Self-serve intake, open to any marketer**
Not gated to the email team. A stakeholder initiates the request themselves, in a surface they already live in.

**Brief structuring**
Free-text request → validated structured brief. The agent identifies what's missing and asks for it *before* anything is built. Nothing proceeds on an incomplete brief.

**Email generation**
Structured brief (or provided copy) → rendered email assembled from the approved component library. Composition from known-good blocks, not free-form HTML.

**Stakeholder preview**
A rendered email the requester reacts to and iterates on directly — before it reaches the email team's queue. This is where the revision rounds get absorbed.

**Brand-guideline vetting**
Automated check against brand and email standards. Pass, flag, or escalate. Nothing reaches the email team unvetted.

### Out of scope — v1

| Deferred | Rationale |
|---|---|
| **Customer.io sync** | v2. The credential-dependent integration is the least interesting part to prove and the most annoying to demo. v1 stubs the boundary cleanly so v2 is an adapter, not a redesign. |
| Send, scheduling, list/segment logic | Stays with the email team. Non-negotiable. |
| Deliverability and client-rendering QA (Litmus etc.) | Human step, existing tooling |
| Net-new template or component design | The agent composes from the approved library; it does not invent components |
| Localization, ABM pages, personas | Opportunities 1, 2, 4 — sequenced after this per `evaluation.md` |

### Explicit non-goals

- **Not replacing the email team.** The final gate stays human in v1, by design.
- **Not autonomous send.** No path from agent output to inbox without human approval.
- **Not a new tool to learn.** If it requires training to file a request, it has failed.

---

## 6. Expectations

### What "working" means

| Metric | Baseline | v1 target |
|---|---|---|
| SLA (request → ready for email team QA) | 2 weeks | **48 hours** |
| Stakeholder revision rounds after build | 3+ | **≤1** |
| First-pass acceptance by email team | n/a | **≥70%** ships with only minor edits |
| Brief completeness at handoff | Frequently incomplete | **100%** — structurally enforced |
| Brand violations reaching the email team | Unmeasured | **<5%** of generated emails |
| Email team hands-on time per email | 2 hrs | **≤30 min** (review, not production) |

### What "adopted" means

Shipping is not adoption. Adoption is measured as:

- **≥60% of eligible requests** flowing through the new intake within 90 days
- **Repeat usage** — stakeholders returning unprompted for a second and third email
- **The old path going quiet** — the real signal; if Slack DMs to the email team continue at volume, the system isn't trusted yet

### Quality bar

The system must fail *loudly and early*, never silently. Specifically:

- **No fabricated content.** If the brief doesn't specify an offer, CTA, or claim, the agent asks — it does not invent. A plausible hallucinated product claim in a customer-facing email is a materially worse outcome than a slow email.
- **Escalate on ambiguity, not just on error.** Low confidence routes to a human with the specific question surfaced.
- **Every output traceable** to a brief field and a library component.

---

## 7. Dependencies and open questions

**Dependencies**
- Access to the approved email component/template library
- Brand and email copy guidelines in a machine-readable form
- Corpus of past emails (est. ~600/yr available) for evals and few-shot grounding
- An intake surface stakeholders already use — Slack strongly preferred over a new form
- Customer.io API access *(v2)*

**Open questions**
1. How standardized is the current template library? Composition-from-components only works if the library genuinely covers the common cases — this is the biggest technical unknown and the first thing to audit.
2. What share of the 40–60 monthly requests are near-duplicates (recurring nurture, event follow-up)? A high share means templated fast-paths handle much of the volume with no LLM judgment at all.
3. Where does approval authority actually sit today — email team, brand, or legal? Determines how many gates v1 needs.
4. What is the real email-influenced pipeline figure? Replaces the §4b placeholder.

---

## 8. Next

Per `evaluation.md`, the proof-of-concept slice is:

**brief → structured brief → email HTML from component library → brand-adherence check with escalation**

Design artifact, repo/cortex plan, evaluation plan, and adoption plan follow.
