<step>select_components</step>

Choose the sequence of email components for this brief.

This step only runs when no deterministic sequence matched the campaign type.
Most emails never reach you — they are assembled from a fixed mapping. You are
the fallback for genuinely novel briefs.

## Rules

1. You may ONLY return component ids from the allowed list below. An id outside
   that list is not a creative choice; it is an error that stops the pipeline.
2. `footer_standard` is mandatory and must be last.
3. Exactly one `cta_button`. `cta_secondary_link` is optional and never primary.
4. Do not select a component whose required slots the brief cannot fill. If the
   brief has no quote, do not select `quote_testimonial`.
5. Prefer the shortest sequence that carries the message. Length is not quality.

## Allowed components

<allowed_components>{{ allowed_components }}</allowed_components>

## Component reference

<component_reference>
{{ component_reference }}
</component_reference>

## The brief

<brief>
{{ brief_json }}
</brief>

## Output

Return JSON only.

{ "components": string[], "reasoning": string, "_confidence": number }
