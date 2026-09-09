# Planning documents

The thinking behind the build in the parent directory. Written in this order,
and each one constrains the next.

| Document | What it settles |
|---|---|
| [`evaluation.md`](evaluation.md) | The scoring framework across all four opportunities, and why email production wins |
| [`requirements.md`](requirements.md) | Business problem, ROI model, audience, scope and success criteria |
| [`tech-stack.md`](tech-stack.md) | Stack choices, what was rejected and why, where deterministic logic ends |
| [`roadmap.md`](roadmap.md) | Six two-week sprints, decision gates, kill criteria |
| [`tasks.md`](tasks.md) | The working checklist those sprints break down into |

## Two known inconsistencies

Flagged rather than quietly patched, since both are judgement calls:

**Customer.io scope.** `requirements.md` §5 lists the Customer.io sync as out of
v1. `tasks.md` and the shipped code both include it. The build is the source of
truth; the requirements doc predates that decision.

**The revenue model rests on an invented input.** `requirements.md` §4b assumes
$20M/year of email-influenced pipeline. That number is a placeholder, labelled
as such in the doc, and needs replacing with a real figure before anyone quotes
the output. The structure of the model holds either way.
