# Voice

This file is passed to the model for the tone assessment step. It is the only
brand input that requires judgment rather than a rule. Anything here that can be
checked with certainty belongs in `rules.yaml` instead.

Edit this in a PR. The eval suite re-runs on every change.

## How we sound

**Plain.** We say what the thing does. We don't build to a reveal, and we don't
use a metaphor where a noun would work.

**Direct.** Second person. Active voice. The reader is doing something, not
having something done to them.

**Specific.** "Cut review time from two weeks to two days" rather than "transform
your workflow." A sentence that would still be true for a different product is a
sentence that isn't doing any work.

**Confident, not loud.** No exclamation marks. No stacked superlatives. If the
thing is good, describing it accurately is enough.

## How we don't sound

- **Hype.** Anything on the banned list in `rules.yaml`, plus the general register
  those words belong to.
- **Corporate hedging.** "We're excited to announce that we'll be introducing" →
  "We're launching."
- **False urgency.** No countdown pressure unless a real deadline exists in the brief.
- **Talking down.** Assume the reader knows their own job.
- **Fake intimacy.** We're not their friend, we're a tool they use. Warm is fine;
  chummy is not.

## Register by audience

| Audience | Note |
|---|---|
| Designers | Assume craft literacy. Never explain what a component is. |
| Developers | Precision over warmth. Specifics, versions, and constraints. |
| Design leaders / execs | Lead with outcome and team impact, not features. |
| Educators / students | Warmer, more explanatory. Still not chummy. |
| Enterprise / IT | Security, governance and admin control up front. |

## Scoring dimensions

The tone step scores each of these 1–5 and must cite specific copy for any score
below 4. A score with no citation is treated as unreliable and escalates.

1. **Plainness** — free of hype and metaphor
2. **Directness** — active, second person, no hedging
3. **Specificity** — claims are concrete and tied to the brief
4. **Register fit** — matches the audience row above
5. **Restraint** — no false urgency, no stacked superlatives

Threshold: mean ≥ 4.0 and no single dimension below 3.
