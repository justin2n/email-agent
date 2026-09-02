"""
Unit tests for the deterministic layer.

Every rule is tested in BOTH directions — that it fires when it should, and
that it stays quiet when it shouldn't. A linter tested only on violations
will happily flag everything and still pass its suite.

stdlib unittest, so `python -m unittest discover tests` works on a clean
machine with no install step.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.escalate import Route, decide                       # noqa: E402
from src.models.brief import Brief                           # noqa: E402
from src.render.assemble import assemble                     # noqa: E402
from src.steps.select import SelectionError, _validate, select_components  # noqa: E402
from src.vet.grounding import check_grounding                # noqa: E402
from src.vet.lint import lint                                # noqa: E402
from src.llm.client import StubClient                        # noqa: E402


def make_brief(**overrides) -> Brief:
    base = dict(
        campaign_type="product_launch",
        audience="designers",
        primary_message="Variables now support nested aliasing.",
        cta_label="Explore variables",
        cta_url="https://www.figma.com/variables",
        send_window="Friday",
    )
    base.update(overrides)
    return Brief(**base)


def render(components, slots, subject="A perfectly reasonable subject line",
           preheader="A preheader long enough to satisfy the minimum character rule."):
    return assemble(components, slots, subject, preheader)


BASE_SLOTS = {
    "headline": "Variables, now with nested aliasing",
    "subhead": "A short note on what changed for design systems teams.",
    "body": "Variables now support nested aliasing, so a token can point at "
            "another token without a manual copy. Design systems stay in sync.",
    "label": "Explore variables",
    "url": "https://www.figma.com/variables",
}


# ======================================================================
class TestBriefSchema(unittest.TestCase):
    """Completeness is decided in code. These tests are the proof."""

    def test_complete_brief_has_no_missing_fields(self):
        self.assertEqual(make_brief().missing_fields(), [])

    def test_missing_base_field_is_detected(self):
        brief = make_brief(cta_url=None)
        self.assertIn("cta_url", brief.missing_fields())

    def test_whitespace_only_counts_as_missing(self):
        self.assertIn("primary_message", make_brief(primary_message="   ").missing_fields())

    def test_conditional_requirements_depend_on_campaign_type(self):
        # A webinar needs event fields; a product launch does not. This is
        # exactly why completeness can't be a flat all-fields-present check.
        launch = make_brief(campaign_type="product_launch")
        webinar = make_brief(campaign_type="webinar_invite")
        self.assertNotIn("event_name", launch.missing_fields())
        self.assertIn("event_name", webinar.missing_fields())

    def test_past_event_date_is_a_validation_issue(self):
        brief = make_brief(campaign_type="webinar_invite", event_name="X",
                           event_date="2020-01-15", event_time="11am PT")
        self.assertIn("date_in_past", [i.code for i in brief.validate()])

    def test_bare_domain_url_is_rejected(self):
        brief = make_brief(cta_url="figma.com/variables")
        self.assertIn("bad_url", [i.code for i in brief.validate()])

    def test_quote_without_attribution_is_rejected(self):
        brief = make_brief(quote="This changed how we work.")
        self.assertIn("missing_attribution", [i.code for i in brief.validate()])

    def test_grounding_corpus_contains_every_supplied_string(self):
        brief = make_brief(supporting_points=["Nested aliasing", "Works in free tier"])
        corpus = brief.grounding_corpus()
        self.assertIn("Nested aliasing", corpus)
        self.assertIn("Explore variables", corpus)


# ======================================================================
class TestComponentSelection(unittest.TestCase):
    """The closed vocabulary. Unknown ids escalate; they are never dropped."""

    def test_known_campaign_type_uses_the_rule_path(self):
        result = select_components(make_brief(), StubClient())
        self.assertEqual(result.path, "rule")
        self.assertEqual(result.confidence, 1.0)

    def test_unknown_component_id_raises_rather_than_being_dropped(self):
        with self.assertRaises(SelectionError):
            _validate(["hero_headline", "definitely_not_a_component"])

    def test_two_primary_ctas_are_rejected(self):
        with self.assertRaises(SelectionError):
            _validate(["hero_headline", "cta_button", "cta_button"])

    def test_footer_is_appended_when_missing(self):
        self.assertEqual(_validate(["hero_headline", "cta_button"])[-1], "footer_standard")

    def test_footer_is_forced_to_last_position(self):
        result = _validate(["hero_headline", "footer_standard", "cta_button"])
        self.assertEqual(result[-1], "footer_standard")
        self.assertEqual(result.count("footer_standard"), 1)

    def test_empty_selection_raises(self):
        with self.assertRaises(SelectionError):
            _validate([])


# ======================================================================
class TestBrandLint(unittest.TestCase):
    """Both directions for every rule."""

    def setUp(self):
        self.clean = render(["hero_headline", "body_text", "cta_button",
                             "footer_standard"], BASE_SLOTS)

    def _rules(self, result):
        return {f.rule for f in result.findings}

    def test_clean_email_produces_no_blocking_findings(self):
        result = lint(self.clean.html, "Variables now support nested aliasing",
                      "A preheader long enough to satisfy the minimum character rule.")
        self.assertTrue(result.passed, f"unexpected blocks: {result.blocks}")

    def test_footer_links_do_not_require_utm(self):
        # Regression: requiring tracking params on the unsubscribe link
        # produced a false positive on every single email.
        result = lint(self.clean.html, "Variables now support nested aliasing",
                      "A preheader long enough to satisfy the minimum character rule.")
        self.assertNotIn("links.missing_utm", self._rules(result))

    def test_short_subject_blocks(self):
        result = lint(self.clean.html, "Hi",
                      "A preheader long enough to satisfy the minimum character rule.")
        self.assertIn("subject.too_short", self._rules(result))

    def test_long_subject_blocks(self):
        result = lint(self.clean.html, "x" * 80,
                      "A preheader long enough to satisfy the minimum character rule.")
        self.assertIn("subject.too_long", self._rules(result))

    def test_exclamation_in_subject_blocks(self):
        result = lint(self.clean.html, "Variables are here now!",
                      "A preheader long enough to satisfy the minimum character rule.")
        self.assertIn("subject.exclamation", self._rules(result))

    def test_missing_preheader_blocks(self):
        result = lint(self.clean.html, "Variables now support nested aliasing", "")
        self.assertIn("preheader.missing", self._rules(result))

    def test_banned_term_blocks(self):
        slots = dict(BASE_SLOTS, body="This is a revolutionary update to variables "
                                      "that changes how design systems work today.")
        html = render(["hero_headline", "body_text", "cta_button", "footer_standard"],
                      slots).html
        result = lint(html, "Variables now support nested aliasing",
                      "A preheader long enough to satisfy the minimum character rule.")
        self.assertIn("content.banned_term", self._rules(result))

    def test_forbidden_cta_label_blocks(self):
        slots = dict(BASE_SLOTS, label="Learn more")
        html = render(["hero_headline", "body_text", "cta_button", "footer_standard"],
                      slots).html
        result = lint(html, "Variables now support nested aliasing",
                      "A preheader long enough to satisfy the minimum character rule.")
        self.assertIn("cta.weak_label", self._rules(result))

    def test_placeholder_text_blocks(self):
        slots = dict(BASE_SLOTS, body="TODO write the actual body copy here before "
                                      "this email goes anywhere near a customer.")
        html = render(["hero_headline", "body_text", "cta_button", "footer_standard"],
                      slots).html
        result = lint(html, "Variables now support nested aliasing",
                      "A preheader long enough to satisfy the minimum character rule.")
        self.assertIn("content.placeholder", self._rules(result))

    def test_image_without_alt_text_blocks(self):
        slots = dict(BASE_SLOTS, image_url="https://cdn.figma.com/a.png", image_alt="")
        html = render(["hero_with_image", "body_text", "cta_button", "footer_standard"],
                      slots).html
        result = lint(html, "Variables now support nested aliasing",
                      "A preheader long enough to satisfy the minimum character rule.")
        self.assertIn("images.no_alt", self._rules(result))

    def test_legal_claim_is_flagged_not_blocked(self):
        slots = dict(BASE_SLOTS, body="Variables are guaranteed to keep your design "
                                      "system in sync across every single file.")
        html = render(["hero_headline", "body_text", "cta_button", "footer_standard"],
                      slots).html
        result = lint(html, "Variables now support nested aliasing",
                      "A preheader long enough to satisfy the minimum character rule.")
        self.assertIn("content.needs_legal_review", self._rules(result))
        self.assertTrue(result.passed, "legal review should flag, not block")

    def test_utm_parameters_are_added_deterministically(self):
        self.assertIn("utm_source=email", self.clean.html)


# ======================================================================
class TestGrounding(unittest.TestCase):
    def test_copy_drawn_from_the_brief_is_clean(self):
        brief = make_brief()
        rendered = render(["hero_headline", "body_text", "cta_button",
                           "footer_standard"], BASE_SLOTS)
        result = check_grounding(rendered.html, "Variables now support nested aliasing",
                                 "A preheader long enough to satisfy the rule.", brief)
        self.assertTrue(result.clean, f"false positive: {result}")

    def test_invented_statistic_is_caught(self):
        brief = make_brief()
        slots = dict(BASE_SLOTS, body="Teams report a 47% reduction in handoff time "
                                      "after switching to nested aliasing.")
        rendered = render(["hero_headline", "body_text", "cta_button",
                           "footer_standard"], slots)
        result = check_grounding(rendered.html, "Variables now support nested aliasing",
                                 "A preheader long enough to satisfy the rule.", brief)
        self.assertIn("47%", result.invented_numbers)

    def test_invented_company_name_is_caught(self):
        brief = make_brief()
        slots = dict(BASE_SLOTS, body="Acme Corporation cut their design review cycle "
                                      "in half using nested aliasing across files.")
        rendered = render(["hero_headline", "body_text", "cta_button",
                           "footer_standard"], slots)
        result = check_grounding(rendered.html, "Variables now support nested aliasing",
                                 "A preheader long enough to satisfy the rule.", brief)
        self.assertTrue(any("Acme" in e for e in result.invented_entities))

    def test_footer_boilerplate_is_not_treated_as_invented(self):
        # Regression: our own office address was flagged on every email.
        brief = make_brief()
        rendered = render(["hero_headline", "body_text", "cta_button",
                           "footer_standard"], BASE_SLOTS)
        result = check_grounding(rendered.html, "Variables now support nested aliasing",
                                 "A preheader long enough to satisfy the rule.", brief)
        self.assertNotIn("94102", result.invented_numbers)


# ======================================================================
class TestEscalationRouter(unittest.TestCase):
    """
    The router is pure. It takes signals and returns a route, so escalation
    behaviour is testable with no model and no rendering.
    """

    def test_clean_signals_proceed(self):
        self.assertEqual(decide().route, Route.PROCEED)

    def test_missing_fields_go_back_to_the_requester(self):
        decision = decide(missing_fields=["cta_url"])
        self.assertEqual(decision.route, Route.REQUESTER)
        self.assertIn("brief.incomplete", [r.rule for r in decision.reasons])

    def test_low_extraction_confidence_goes_back_to_the_requester(self):
        self.assertEqual(decide(extraction_confidence=0.4).route, Route.REQUESTER)

    def test_model_fallback_selection_is_flagged(self):
        decision = decide(selection_path="model", selection_confidence=0.9)
        self.assertEqual(decision.route, Route.REVIEW)

    def test_low_confidence_model_fallback_blocks(self):
        decision = decide(selection_path="model", selection_confidence=0.2)
        self.assertEqual(decision.route, Route.BLOCK)

    def test_unknown_slots_block(self):
        self.assertEqual(decide(unknown_slots=["made_up_slot"]).route, Route.BLOCK)

    def test_most_severe_route_wins(self):
        decision = decide(missing_fields=["cta_url"], unknown_slots=["nope"])
        self.assertEqual(decision.route, Route.BLOCK)

    def test_uncited_low_voice_score_is_not_trusted(self):
        decision = decide(voice_result={
            "scores": {"plainness": 3, "directness": 5, "specificity": 5,
                       "register_fit": 5, "restraint": 5},
            "mean": 4.6, "citations": {},
        })
        self.assertIn("voice.uncited_score", [r.rule for r in decision.reasons])

    def test_every_reason_names_its_rule(self):
        # An escalation that can't say what fired wastes the reviewer's time.
        decision = decide(missing_fields=["cta_url"], truncated_slots=["headline"])
        for reason in decision.reasons:
            self.assertTrue(reason.rule and reason.message)


# ======================================================================
class TestAssembly(unittest.TestCase):
    def test_model_output_is_html_escaped(self):
        slots = dict(BASE_SLOTS, headline="<script>alert('xss')</script>")
        html = render(["hero_headline", "cta_button", "footer_standard"], slots).html
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_plaintext_alternative_is_generated(self):
        rendered = render(["hero_headline", "body_text", "cta_button",
                           "footer_standard"], BASE_SLOTS)
        self.assertIn("Unsubscribe", rendered.text)
        self.assertIn(BASE_SLOTS["headline"], rendered.text)

    def test_components_render_in_the_given_order(self):
        html = render(["hero_headline", "body_text", "cta_button",
                       "footer_standard"], BASE_SLOTS).html
        self.assertLess(html.index(BASE_SLOTS["headline"]), html.index("Explore variables"))


if __name__ == "__main__":
    unittest.main(verbosity=2)


# ======================================================================
class TestAnswerHandling(unittest.TestCase):
    """
    Regression tests for bugs the Slack walkthrough exposed.

    Every one of these was a real failure found by watching the marketer-facing
    flow rather than the CLI. Prose answers need coercing into typed fields, and
    positional mapping breaks the moment someone answers out of order.
    """

    def test_prose_campaign_type_is_coerced_to_the_enum(self):
        from src.steps.intake import normalise_answer
        # A requester types "product launch", the field wants "product_launch".
        self.assertEqual(normalise_answer("campaign_type", "product launch"),
                         "product_launch")

    def test_partial_campaign_type_resolves(self):
        from src.steps.intake import normalise_answer
        self.assertEqual(normalise_answer("campaign_type", "launch"), "product_launch")

    def test_uncoercible_value_returns_none_rather_than_garbage(self):
        from src.steps.intake import normalise_answer
        # Storing the raw string would fail validation with a message the
        # requester can't act on. None means "ask again", which is honest.
        self.assertIsNone(normalise_answer("campaign_type", "banana"))

    def test_bare_domain_is_upgraded_to_https(self):
        from src.steps.intake import normalise_answer
        self.assertEqual(normalise_answer("cta_url", "figma.com/dev-mode"),
                         "https://figma.com/dev-mode")

    def test_free_text_is_not_accepted_as_a_url(self):
        from src.steps.intake import normalise_answer
        self.assertIsNone(normalise_answer("cta_url", "Open Dev Mode"))

    def test_urls_are_claimed_by_shape_not_position(self):
        from src.steps.intake import match_answers
        # She answered a question that wasn't asked, so a positional zip would
        # put "Open Dev Mode" in cta_url and shift everything after it.
        matched = match_answers(
            ["campaign_type", "cta_label", "cta_url"],
            ["product launch",
             "Developers can pull production-ready specs",
             "Open Dev Mode",
             "https://www.figma.com/dev-mode"],
        )
        self.assertEqual(matched["cta_url"], "https://www.figma.com/dev-mode")
        self.assertEqual(matched["campaign_type"], "product launch")

    def test_apply_answers_never_overwrites_a_filled_field(self):
        from src.steps.intake import apply_answers
        brief = make_brief(cta_label="Original label")
        merged = apply_answers(brief, {"cta_label": "Replacement"})
        self.assertEqual(merged.cta_label, "Original label")

    def test_vague_ask_is_not_treated_as_the_primary_message(self):
        from src.llm.stub_responses import _primary_message
        # "Can we get something out about X?" names a topic, not a message.
        # Accepting it would skip the most important question in the flow.
        self.assertIsNone(_primary_message(
            "can we get something out about Dev Mode Inspect? For developers."))
        self.assertIsNotNone(_primary_message(
            "Developers can pull production-ready specs from a Figma file."))

    def test_slack_mention_is_stripped_from_the_request(self):
        from src.llm.stub_responses import MENTION_RE
        self.assertEqual(
            MENTION_RE.sub("", "@Email Agent can we ship this", count=1),
            "can we ship this",
        )

    def test_requester_route_always_carries_a_question(self):
        from src.llm.client import StubClient
        from src.slack.app import ThreadState, handle_new_request, handle_answers
        # An empty question list is a dead end for the requester and the
        # fastest way to lose their trust in the tool.
        state = ThreadState(thread_ts="t", channel="c", requester="p",
                            raw_request="@Email Agent something about Dev Mode "
                                        "for developers, needs to go Tuesday")
        state, _ = handle_new_request(state, client=StubClient())
        state, _ = handle_answers(state, "product launch\nDevelopers get specs "
                                         "without waiting on a designer\n"
                                         "Open Dev Mode\nhttps://www.figma.com/dev",
                                  client=StubClient())
        if state.status == "awaiting_answers":
            self.assertTrue(state.pending_questions,
                            "routed back to requester with nothing to answer")


# ======================================================================
class TestCopyQuality(unittest.TestCase):
    """
    The offline copy engine has to produce something a marketer would
    recognise as an email. Echoing the brief back is grounded but obviously
    machine-made, and an unshowable demo is a failed demo.
    """

    BRIEF = ("We're launching Dev Mode Inspect for developers next Tuesday.\n"
             "Developers can pull production-ready specs straight from a Figma file.\n"
             "- Copy CSS, iOS and Android values from any layer\n"
             "- See exactly what changed between versions\n"
             "- Works in the free tier for every developer seat\n"
             "Button \"Open Dev Mode\" -> https://www.figma.com/dev-mode\n"
             "Send Tuesday.")

    def _run(self, text):
        from src.llm.client import StubClient
        from src.pipeline import run as run_pipeline
        return run_pipeline(text, client=StubClient(), persist_run=False)

    def test_subject_is_not_the_raw_request_echoed_back(self):
        result = self._run(self.BRIEF)
        self.assertNotIn("We're launching", result.subject)
        self.assertGreaterEqual(len(result.subject), 15)

    def test_feature_titles_are_labels_not_truncated_sentences(self):
        # "Copy CSS, iOS and" reads as a bug; "Copy CSS" reads as a label.
        result = self._run(self.BRIEF)
        for slot, value in result.generation.slots.items():
            if slot.endswith("_title") and value:
                self.assertFalse(value.rstrip().endswith((" and", " the", " in", " of")),
                                 f"{slot} truncated mid-phrase: {value!r}")

    def test_send_timing_does_not_leak_into_body_copy(self):
        result = self._run(self.BRIEF)
        self.assertNotIn("next Tuesday", result.generation.slots.get("body", ""))

    def test_preheader_differs_from_subject(self):
        # The preheader is the third line the reader sees, not a repeat.
        result = self._run(self.BRIEF)
        self.assertNotEqual(result.subject.strip(),
                            result.generation.preheader.strip())

    def test_change_request_is_not_treated_as_content(self):
        # Regression: an iteration produced "Requested change: Lead is here"
        # as the subject line.
        result = self._run(self.BRIEF + "\n\nRequested change: Lead on the free tier")
        self.assertNotIn("Requested change", result.subject)
