#!/usr/bin/env python3
"""Pre-deploy review blockers on the demo story, display side only (the core records are not changed):
B1 a cancellation that names the procedure by a shorter name ('Surgery tomorrow morning has been cancelled' for 'Hip
surgery') is read as the cancellation of that procedure; B2 a cancelled going-home or follow-up plan is told in its own
words and leaves What's next and the Going home cell; S5 the toast keeps the core's headline precedence (two different
answers); S6 a modal negation ('may not go ahead') keeps the plan upcoming. Stdlib only:
  python agent/test_review_blockers_display.py
"""
from __future__ import annotations

import copy
import html
import re
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from episode import Episode, load_scenario  # noqa: E402
import timeline_html as T  # noqa: E402

STORY = load_scenario(HERE.parent / "care_cases" / "episode_hip_fracture.json")
TZ = "Europe/London"
AFTER_U02 = "2026-10-19T15:00:00+01:00"   # a Monday: tomorrow is Tue 20 Oct
AFTER_U07 = "2026-10-22T18:00:00+01:00"   # a Thursday: Saturday is 24 Oct, Monday 26 Oct


def visible(markup: str) -> str:
    """The words a reader sees without opening a Source or history drawer."""
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", re.sub(r"<details\b.*?</details>", " ", markup))).split())


def story(upto: str) -> Episode:
    ep = Episode({**STORY, "updates": []})
    for u in STORY["updates"]:
        ep.add_update(copy.deepcopy(u))
        if u["update_id"] == upto:
            return ep
    raise AssertionError(upto)


class Blockers(unittest.TestCase):
    def add(self, ep: Episode, uid: str, at: str, text: str, facts: list[dict]) -> dict:
        entry = ep.add_update({"update_id": uid, "at": at, "kind": "recording", "speaker": "Ward nurse",
                               "author": "anna", "text": text}, facts=facts)
        self.assertEqual(entry["rejected"], [])
        return entry

    def surfaces(self, ep: Episode) -> dict:
        view = T.presentation_model(ep, "anna", TZ)
        state = ep.status(TZ)
        return {"hero": visible(T.hero_html(ep, state, TZ, ep.members["anna"], presentation=view)),
                "side": visible(T.side_html(ep, state, TZ, "anna", presentation=view)),
                "timeline": visible(T.timeline_html(ep, "anna", TZ, presentation=view))}

    def surgery(self, quote: str, when_text: str) -> tuple[Episode, dict]:
        ep = story("u02")
        e = self.add(ep, "rb1", AFTER_U02, quote + ".", [{"type": "procedure_planned", "what": "Hip surgery", "quote": quote,
                                                          "when": "2026-10-20", "when_text": when_text}])
        return ep, e

    def test_b1_a_cancellation_by_a_shorter_name_is_not_planned(self):
        for quote, when_text in (("Surgery tomorrow morning has been cancelled", "tomorrow morning"),
                                 ("The operation tomorrow has been cancelled", "tomorrow"),
                                 ("Her surgery tomorrow has been cancelled", "tomorrow")):
            with self.subTest(quote=quote):
                ep, e = self.surgery(quote, when_text)
                shown = self.surfaces(ep)
                self.assertEqual(T.display_headline(e), quote)
                self.assertNotIn("Hip surgery planned", shown["hero"] + shown["side"])
                self.assertNotIn("Waiting for hip surgery", shown["hero"])
                self.assertIn(quote, shown["timeline"])
                self.assertEqual(ep.procedures and next(iter(ep.procedures.values()))["status"], "planned")   # core unchanged

    def test_b1_keeps_a_conditional_cancellation_a_rebooking_and_a_postponement_to_a_date(self):
        for quote, when_text in (("Surgery tomorrow will be cancelled if her blood results are low", "tomorrow"),
                                 ("Surgery tomorrow was cancelled and is rebooked for Friday", "tomorrow"),
                                 ("Surgery tomorrow has been postponed to Friday", "tomorrow")):
            with self.subTest(quote=quote):
                ep, e = self.surgery(quote, when_text)
                shown = self.surfaces(ep)
                self.assertIn("Hip surgery", shown["side"])   # planned, or two different answers to ask about
                self.assertIn("Waiting for hip surgery", shown["hero"])
                self.assertNotEqual(T.display_headline(e), quote)

    def test_b2_a_cancelled_going_home_plan_is_told_in_its_own_words(self):
        quote = "Going home on Saturday morning has been cancelled"
        ep = story("u07")
        e = self.add(ep, "rb2", AFTER_U07, quote + ".", [{"type": "expected_discharge", "quote": quote,
                                                         "when": "2026-10-24", "when_text": "Saturday morning"}])
        shown = self.surfaces(ep)
        self.assertEqual(T.display_headline(e), quote)
        self.assertNotIn("Expected to go home: Sat 24 Oct", shown["hero"] + shown["side"])
        self.assertNotIn("Going home Sat 24 Oct", shown["hero"])
        self.assertNotIn("Planned " + quote, shown["hero"])
        self.assertIn(quote, shown["timeline"])
        self.assertEqual(ep.slots["expected_discharge"]["fact"]["quote"], quote)   # core unchanged

    def test_b2_a_cancelled_follow_up_leaves_whats_next(self):
        quote = "The fracture clinic on Monday has been cancelled"
        ep = story("u07")
        e = self.add(ep, "rb3", AFTER_U07, quote + ".", [{"type": "follow_up", "what": "Fracture clinic", "quote": quote,
                                                         "when": "2026-10-26", "when_text": "Monday"}])
        shown = self.surfaces(ep)
        self.assertEqual(T.display_headline(e), quote)
        self.assertNotIn("Fracture clinic: Mon 26 Oct", shown["hero"] + shown["side"] + shown["timeline"])
        self.assertIn(quote, shown["timeline"])
        self.assertIn("Expected to go home: Sat 24 Oct morning", shown["side"])   # the other plan stays

    def test_b2_keeps_a_conditional_or_rebooked_going_home_plan(self):
        for quote in ("Going home on Saturday morning may be cancelled",
                      "Going home on Saturday morning was cancelled and is rebooked for Sunday"):
            with self.subTest(quote=quote):
                ep = story("u07")
                self.add(ep, "rb4", AFTER_U07, quote + ".", [{"type": "expected_discharge", "quote": quote,
                                                             "when": "2026-10-24", "when_text": "Saturday morning"}])
                self.assertIn("Expected to go home: Sat", self.surfaces(ep)["side"])

    def test_s5_the_toast_keeps_the_cores_two_answers_headline(self):
        # u07b (the demo's two different answers about going home) with a cancelled test in the same recording: the
        # cancelled test ranks first by type, but the news of the update is the two answers (Episode.render).
        ep = story("u07")
        u07b = copy.deepcopy(next(u for u in STORY["updates"] if u["update_id"] == "u07b"))
        xray = "The X-ray tomorrow has been cancelled"
        u07b["text"] += " " + xray + "."
        e = ep.add_update(u07b, facts=[*u07b["recorded_extraction"],
                                       {"type": "procedure_planned", "what": "X-ray", "quote": xray,
                                        "when": "2026-10-24", "when_text": "tomorrow"}])
        self.assertEqual(e["rejected"], [])
        self.assertTrue(any(x.get("two_answers") for x in e["lines"]))
        self.assertTrue(e["headline"].startswith("Two different answers about going home"), e["headline"])
        self.assertEqual(T.display_headline(e), e["headline"])

    def test_s6_a_modal_negation_keeps_the_procedure_upcoming(self):
        ep, e = self.surgery("Surgery may not go ahead tomorrow", "tomorrow")
        shown = self.surfaces(ep)
        self.assertIn("What's next", shown["side"])
        self.assertIn("Hip surgery", shown["side"])   # planned, or two different answers to ask about
        self.assertIn("Waiting for hip surgery", shown["hero"])
        ep, e = self.surgery("Surgery will not go ahead tomorrow", "tomorrow")
        shown = self.surfaces(ep)
        self.assertNotIn("Hip surgery", shown["side"])
        self.assertNotIn("Waiting for hip surgery", shown["hero"])


if __name__ == "__main__":
    unittest.main()
