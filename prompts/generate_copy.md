<step>generate_copy</step>

Write the copy for one marketing email, filling named slots.

## The one rule that matters

Every factual claim in your output must trace to the brief below. Products,
prices, dates, offers, statistics, customer names, capabilities — if it is not
in the brief, it does not go in the email.

You are not being asked to write a *good* email out of a thin brief. You are being
asked to write an *accurate* email out of whatever the brief actually contains. A
thin brief should produce a short email. Padding it with invented specifics is the
worst possible outcome, worse than returning almost nothing, because it looks
finished and a human may not catch it.

If a slot cannot be filled from the brief, return an empty string for it. The
pipeline will escalate. That is working as intended.

## Voice

<voice>
{{ voice_guidance }}
</voice>

## Hard constraints

- Respect every character limit in the slot list. These are enforced downstream.
- No exclamation marks.
- No terms from the banned list: <banned_terms>{{ banned_terms }}</banned_terms>
- CTA labels must be specific. "Learn more" and "Click here" are rejected by the linter.
- Subject line 15-60 characters, sentence case.
- Preheader 40-100 characters, and it must not repeat the subject line.

## The brief

<primary_message>{{ primary_message }}</primary_message>
<audience>{{ audience }}</audience>
<supporting_points>
{{ supporting_points }}
</supporting_points>
<offer>{{ offer }}</offer>
<cta_label>{{ cta_label }}</cta_label>
<cta_url>{{ cta_url }}</cta_url>
<event_name>{{ event_name }}</event_name>
<event_date>{{ event_date }}</event_date>
<event_time>{{ event_time }}</event_time>
<event_duration>{{ event_duration }}</event_duration>
<event_location>{{ event_location }}</event_location>
<quote>{{ quote }}</quote>
<attribution_name>{{ attribution_name }}</attribution_name>
<attribution_role>{{ attribution_role }}</attribution_role>
<resource_title>{{ resource_title }}</resource_title>
<resource_url>{{ resource_url }}</resource_url>
<image_url>{{ image_url }}</image_url>
<image_alt>{{ image_alt }}</image_alt>

## Slots to fill

<slots>{{ slot_list }}</slots>

<slot_limits>
{{ slot_limits }}
</slot_limits>

## Output

Return JSON only.

{
  "slots": { "<slot_name>": "<copy>" },
  "subject_options": [string, string, string],
  "preheader": string,
  "_confidence": number
}
