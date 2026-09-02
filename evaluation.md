# Evaluate & Prioritize

Four opportunities, one framework, one recommendation.

---

## 1. The framework

The role is measured on **agents live, hours saved, revenue driven**. So the framework can't just rank by prize size — it has to reward things that actually ship and get used. Six criteria:

| Criterion | Weight | Why it's here |
|---|---|---|
| Hours saved (annualized, addressable) | 25% | Direct objective |
| Revenue driven (size × attributability) | 25% | Direct objective |
| Feasibility / time-to-live-agent | 20% | "Agents live" is a measure; a 9-month build scores zero all year |
| Data availability & eval-ability | 15% | You can't ship what you can't verify |
| Reach (marketers × frequency) | 10% | Frequency drives habit; annual workflows never become muscle memory |
| Compounding / reusability | 5% | Whether it builds the spine for the next three |

Two of these are non-obvious and worth defending:

**Eval-ability, not just data availability.** An agent whose output you can't grade is an agent you can't trust in production. This is the criterion that quietly kills one of the four.

**Frequency inside reach.** Localization runs 8×/year. Email runs ~600×/year. The same number of marketers touched means very different odds the thing survives past launch week.

---

## 2. Scoring

Scored 1–5 relative to the set, not absolute.

| | Localization | ABM pages | Email | Personas |
|---|---|---|---|---|
| Hours saved (25%) | 2 | 2 | 5 | 1 |
| Revenue (25%) | 4 | 5 | 4 | 2 |
| Feasibility (20%) | 2 | 4 | 5 | 3 |
| Data & eval (15%) | 2 | 3 | 5 | 2 |
| Reach (10%) | 2 | 2 | 5 | 3 |
| Compounding (5%) | 3 | 3 | 5 | 4 |
| **Weighted total** | **2.55** | **3.35** | **4.75** | **2.15** |

### The hours math, since it drives the biggest gap

| Opportunity | Annual hours today | Notes |
|---|---|---|
| Email | ~1,200 – 2,000 | 50 requests/mo × 2 hrs build = 1,200 before intake and revision rounds; add ~1.5 hrs of stakeholder back-and-forth per email and it's ~2,000 |
| Localization | ~560 | 70 hrs × 8 campaigns |
| ABM pages | ~60 | 25 pages × 2.5 hrs. The other ~560 hrs is *latent*, not saved |
| Personas | ~120 | 2–4 weeks of researcher/PMM effort, ~1×/year |

Email's addressable pool is roughly 3–4× localization and 20× ABM's actual current spend.

---

## 3. Recommendation: **Email production**

Not because it's the most exciting — it isn't — but because it's the only one that wins on hours, feasibility, and evidence simultaneously, and because **it's the substrate for the other three.**

Email is the most constrained medium in marketing: fixed width, modular blocks, a finite component library, a destination with an API. That constraint is what makes it automatable. Localization and ABM are both harder versions of "generate a branded asset and route it for review" — and the pieces built for email (brief intake, structured brief schema, brand-adherence vetting, HITL gate, system-of-record sync) are ~60% of what those need.

### The sequencing argument is the real argument

1. **Email** — builds the spine, on the highest-volume workflow, where ~600 past emails exist to eval against.
2. **ABM pages** — reuses the brief schema, copy generation, and brand vet; swaps Customer.io for a page builder and adds Snowflake as the trigger.
3. **Localization** — localizes the emails and pages the first two now generate, instead of standing up a parallel pipeline.
4. **Personas** — becomes a *context service* that improves copy in all three, rather than a standalone chatbot with no consumer.

---

## 4. Tradeoffs weighed

**ABM has the better slide; email has the better business case.**
$80K ACV × 250 accounts × 10% lift is the cleanest revenue math in the set, and it's the obvious pick for that reason. I didn't take it because the hours pool is ~60/year and the reach is one small team on a quarterly cadence. It's a strong *second* build — and more likely to succeed after email, because brand vetting and stakeholder preview will already be solved.

**Localization's hardest problem isn't an AI problem.**
"Half the time the translation lands flat culturally" is a reviewer-capacity problem. An agent can generate ten regional variants in minutes; it cannot tell you whether the Japanese one is embarrassing. Without in-region reviewers on staff, the bottleneck moves rather than disappears — and gets worse, because there's now 10× more to review. Add layout reflow across PDF and ad creative (German runs ~30% longer than English) and it's a genuinely hard engineering problem on top of a staffing one.

**Personas is the one I'd most want to build and the one I'd defend least.**
Its failure mode is uniquely bad: a persona bot that confidently invents what customers think is *worse than no persona*, because the output is unfalsifiable. You can't grade "how would this persona react to this subject line" without doing the research the tool was meant to replace. Every other opportunity has a ground truth to eval against; this one doesn't. That's what drops it to last despite being the most interesting brief.

**The honest risk in this pick.**
Email's revenue attribution is weaker than ABM's. "Faster SLA → more sends → more pipeline" has a soft link in the middle. The mitigation is to instrument *campaign throughput and test velocity* as leading indicators, hold a genuine before/after on sends-per-month, and not claim credit for whole-channel revenue.

---

## 5. What Part 2 builds

Proposed slice for the proof-of-concept:

**brief → structured brief → email HTML from a component library → brand-adherence check with escalation**

Stopping short of the live Customer.io sync and stubbing that boundary — the API integration is the least interesting part to demo and the most credential-dependent to make work.
