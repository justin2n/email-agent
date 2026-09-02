<step>clarify_gaps</step>

Some required fields are missing from a marketing email brief. Write the questions
that close those gaps.

## Rules

1. One question per missing field. Do not ask about fields that are already filled.
2. Write for a busy marketer in Slack. Short, specific, answerable in one line.
3. Where the house style has an opinion, say so briefly — e.g. for a CTA label,
   note that something specific beats "Learn more".
4. Do not suggest an answer. A suggested answer becomes the answer, and then the
   brief records a decision the requester never actually made.
5. Never ask more than five questions in one round. If more than five are missing,
   ask the five most blocking and note that there are others.

## Missing fields

<missing_fields>{{ missing_fields }}</missing_fields>

## What we already have

<known>
{{ known_fields }}
</known>

## Output

Return JSON only.

{ "questions": string[], "_confidence": number }
