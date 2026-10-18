#!/usr/bin/env python3
"""A cancellation the care team words without 'cancel' ('called off', 'withdrawn', 'scrapped', 'put off', 'dropped from
the list', 'no longer going ahead', 'will not go ahead') and a postponement or delay without a new date are read by the
display as a cancellation is (timeline_html._test_not_upcoming, for a test topic and a procedure alike): the timeline
card, Right now, What's next and the 'Timeline updated: ...' message (display_headline) show the source's own words,
never '<what> planned' or a 'Planned' label. A postponement to a new date ('postponed to Friday'), a re-plan after the
change, and a negated, modal or conditional change ('has not been called off', 'may be called off if ...') keep the
plan. The core procedure record is not changed. Stdlib only:
  python agent/test_cancel_vocabulary.py
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import timeline_html as T  # noqa: E402
from test_display_cancel_toast import AT, TZ, DisplayCase, episode, plan, visible  # noqa: E402


class TestProcedureCancelVocabulary(DisplayCase):
    def assert_not_planned(self, what: str, quote: str, **fields):
        ep = episode()
        entry = self.add(ep, "op", [plan(what, quote, **fields)])
        before = ep.to_snapshot()
        view, out = self.surfaces(ep)
        self.assertEqual(view["next"], [])
        for name, markup in out.items():
            with self.subTest(surface=name):
                words = visible(markup)
                self.assertNotIn(f"{what} planned", words)
                self.assertNotIn(f"Waiting for {what.lower()}", words)
                self.assertNotRegex(words, r"\bPlanned\b")
        for name in ("timeline", "hero"):
            self.assertIn(T.esc(quote), out[name])   # the source's own words carry the change
        self.assertIn("<span>Procedure</span>", out["timeline"])
        self.assertEqual(T.display_headline(entry), quote)
        self.assertEqual(ep.to_snapshot(), before)   # display only
        self.assertEqual(ep.procedures[re.sub(r"[^a-z0-9]+", " ", what.lower()).strip()]["status"], "planned")

    def assert_planned(self, what: str, quote: str, **fields):
        ep = episode()
        entry = self.add(ep, "op", [plan(what, quote, **fields)])
        view, out = self.surfaces(ep)
        self.assertEqual(len(view["next"]), 1)
        self.assertTrue(view["next"][0]["text"].startswith(f"{what} planned"))
        self.assertIn(f"Waiting for {what.lower()}", visible(out["hero"]))
        self.assertEqual(T.display_headline(entry), entry["headline"])
        return view

    def test_cancellations_worded_without_cancel_are_not_planned(self):
        for what, quote in (("Operation", "The operation has been called off"),
                            ("Surgery", "Surgery is withdrawn"),
                            ("Appointment", "The appointment has been called off"),
                            ("Operation", "We have called off the operation"),
                            ("Surgery", "Surgery has been scrapped"),
                            ("Surgery", "Surgery has been put off"),
                            ("Surgery", "Surgery was dropped from the theatre list"),
                            ("Operation", "The operation is no longer going ahead"),
                            ("Surgery", "Surgery will not go ahead")):
            with self.subTest(quote=quote):
                self.assert_not_planned(what, quote)

    def test_a_postponement_or_delay_without_a_new_date_is_not_upcoming(self):
        for quote in ("Surgery is postponed", "Surgery is delayed", "Surgery has been postponed until further notice",
                      "Surgery has been delayed to a later date"):
            with self.subTest(quote=quote):
                self.assert_not_planned("Surgery", quote)

    def test_a_postponement_to_a_new_date_stays_planned_for_it(self):
        view = self.assert_planned("Surgery", "Surgery is postponed to Friday", when_text="Friday")
        self.assertEqual([item["text"] for item in view["next"]], ["Surgery planned: Fri 23 Oct"])
        for quote, fields in (("Surgery has been put off until Friday", {"when_text": "Friday"}),
                              ("Surgery was postponed from Thursday to Friday", {"when_text": "Friday"}),
                              ("Surgery has been delayed until 14:00", {"when_text": "14:00"})):
            with self.subTest(quote=quote):
                self.assert_planned("Surgery", quote, **fields)

    def test_a_negated_modal_conditional_or_replanned_change_keeps_the_plan(self):
        for what, quote, fields in (("Operation", "The operation may be called off if her fever returns", {}),
                                    ("Surgery", "Surgery has not been called off", {}),
                                    ("Surgery", "Surgery has not been withdrawn and goes ahead on Friday", {"when_text": "Friday"}),
                                    ("Surgery", "We have not called off the surgery", {}),
                                    ("Surgery", "Surgery is planned for Friday but may be delayed", {"when_text": "Friday"}),
                                    ("Surgery", "Surgery was called off today and is rebooked for Friday", {"when_text": "Friday"}),
                                    ("Surgery", "Surgery is planned for Friday and she was dropped off by her son",
                                     {"when_text": "Friday"})):
            with self.subTest(quote=quote):
                self.assert_planned(what, quote, **fields)


class TestTestTopicCancelVocabulary(DisplayCase):
    def topic(self, quote: str):
        ep = episode()
        entry = self.add(ep, "mri", [plan("MRI", quote)])
        view = T.presentation_model(ep, "anna", TZ, now=AT)
        topic, = view["test_topics"]
        return ep, entry, view, topic

    def test_a_scrapped_or_called_off_test_is_not_upcoming_and_shows_its_words(self):
        for quote in ("The MRI was scrapped", "The MRI has been called off", "The MRI is withdrawn",
                      "The MRI was dropped from the list", "The MRI will not go ahead",
                      "The MRI is no longer going ahead", "We have scrapped the MRI", "The MRI is postponed"):
            with self.subTest(quote=quote):
                ep, entry, view, topic = self.topic(quote)
                self.assertFalse(topic["upcoming"])
                self.assertEqual(view["next"], [])
                shown = T.test_topics_html(ep, [topic], TZ, lambda entry: None).split("<details>")[0]
                self.assertIn(T.esc(quote), shown)
                self.assertEqual(T.display_headline(entry), quote)
                self.assertEqual(ep.procedures["mri"]["status"], "planned")   # display only

    def test_a_negated_modal_conditional_or_replanned_change_keeps_the_test_upcoming(self):
        for quote in ("The MRI may be called off if the scanner is down", "The MRI has not been called off",
                      "The MRI may not go ahead", "We have not scrapped the MRI",
                      "The MRI was called off but has been rebooked for Friday", "The MRI is postponed to Friday"):
            with self.subTest(quote=quote):
                ep, entry, view, topic = self.topic(quote)
                self.assertTrue(topic["upcoming"])
                self.assertEqual(len(view["next"]), 1)
                self.assertEqual(T.display_headline(entry), entry["headline"])


if __name__ == "__main__":
    unittest.main(verbosity=1)
