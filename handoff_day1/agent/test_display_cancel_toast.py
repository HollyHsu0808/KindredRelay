#!/usr/bin/env python3
"""A care-team quote that says a procedure was cancelled is kept as procedure_planned by the core (it has no cancelled
state), so the display reads the cancellation from the quote as a test topic does (_test_not_upcoming): the timeline
card, Right now and What's next show the source's own words, never '<what> planned' or a 'Planned' label, unless a
re-plan follows the cancellation ('cancelled today and is rebooked for Friday') or it is only possible ('may be
cancelled if ...'). The headline a message about a new update uses (display_headline: the page's 'Timeline updated:
...') is the one its timeline card shows. The core procedure record is not changed. Stdlib only:
  python agent/test_display_cancel_toast.py
"""
from __future__ import annotations

import html
import re
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from episode import Episode, load_scenario  # noqa: E402
import timeline_html as T  # noqa: E402

SCENARIO = HERE.parent / "care_cases" / "episode_hip_fracture.json"
AT = "2026-10-21T10:00:00+01:00"   # a Wednesday: tomorrow is Thu 22 Oct, Friday 23 Oct
TZ = "Europe/London"
CANCELLED = "Surgery has been cancelled"
REBOOKED = "Surgery was cancelled today and is rebooked for Friday"
NOT_OPERATING = "The surgeon will not operate tomorrow morning"


def episode() -> Episode:
    """The demo story's patient and family with no updates yet (the two-different-answers pair left out)."""
    scenario = load_scenario(SCENARIO)
    return Episode({**scenario, "updates": [u for u in scenario["updates"] if u["update_id"] not in ("u07b", "u07c")]})


def plan(what: str, quote: str, **fields) -> dict:
    return {"type": "procedure_planned", "what": what, "quote": quote, **fields}


def visible(markup: str) -> str:
    """The words a reader sees without opening a Source or history drawer."""
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", re.sub(r"<details\b.*?</details>", " ", markup))).split())


class DisplayCase(unittest.TestCase):
    def add(self, ep: Episode, uid: str, facts: list[dict], text: str | None = None, at: str = AT) -> dict:
        entry = ep.add_update({"update_id": uid, "at": at, "kind": "recording", "speaker": "Doctor", "author": "anna",
                               "text": text or ". ".join(f["quote"] for f in facts) + "."}, facts=facts)
        self.assertEqual(entry["rejected"], [])
        return entry

    def surfaces(self, ep: Episode) -> tuple[dict, dict]:
        view = T.presentation_model(ep, "anna", TZ)
        state = ep.status(TZ)
        return view, {"timeline": T.timeline_html(ep, "anna", TZ, presentation=view),
                      "hero": T.hero_html(ep, state, TZ, ep.members["anna"], presentation=view),
                      "side": T.side_html(ep, state, TZ, "anna", presentation=view)}


class TestCancelledProcedureDisplay(DisplayCase):
    def assert_not_planned(self, ep: Episode, quote: str, what: str):
        before = ep.to_snapshot()
        view, out = self.surfaces(ep)
        self.assertEqual(view["next"], [])
        for name, markup in out.items():
            with self.subTest(surface=name):
                words = visible(markup)
                self.assertNotIn(f"{what} planned", words)
                self.assertNotIn(f"Waiting for {what.lower()}", words)
                self.assertNotIn("What's next", words)
                self.assertNotRegex(words, r"\bPlanned\b")
        for name in ("timeline", "hero"):
            self.assertIn(T.esc(quote), out[name])   # the source's own words carry the cancellation
        self.assertIn(f'data-headline="{T.esc(quote)}"', out["timeline"])
        self.assertIn("<span>Procedure</span>", out["timeline"])   # the key event's category, not 'Planned'
        self.assertEqual(ep.to_snapshot(), before)   # display only
        self.assertEqual(ep.procedures[re.sub(r"[^a-z0-9]+", " ", what.lower()).strip()]["status"], "planned")

    def assert_planned(self, ep: Episode, what: str, headline: str):
        view, out = self.surfaces(ep)
        self.assertEqual([item["text"] for item in view["next"]], [headline])
        words = {name: visible(markup) for name, markup in out.items()}
        self.assertIn(headline, words["timeline"])
        self.assertIn("What's next " + "Your time; a date without a time is the hospital's date " + headline, words["side"])
        self.assertIn(f"Waiting for {what.lower()}", words["hero"])
        self.assertIn(f"Planned {headline}", words["hero"])

    def test_a_cancelled_surgery_is_not_shown_as_planned_anywhere(self):
        ep = episode()
        self.add(ep, "op", [plan("Surgery", CANCELLED)])
        self.assert_not_planned(ep, CANCELLED, "Surgery")

    def test_other_cancellation_wordings(self):
        for what, quote, fields in (("Operation", "The operation on Friday has been cancelled", {"when_text": "Friday"}),
                                    ("Surgery", "Surgery tomorrow morning was cancelled", {"when_text": "tomorrow morning"}),
                                    ("Surgery", "We have cancelled the surgery", {})):
            with self.subTest(quote=quote):
                ep = episode()
                self.add(ep, "op", [plan(what, quote, **fields)])
                self.assert_not_planned(ep, quote, what)

    def test_a_rebooked_or_only_possible_cancellation_keeps_the_plan(self):
        for quote, fields, headline in (
                (REBOOKED, {"when_text": "Friday"}, "Surgery planned: Friday"),   # the core leaves two stated days as written
                ("Surgery is planned for Friday but may be cancelled if the theatre is busy", {"when_text": "Friday"},
                 "Surgery planned: Friday")):
            with self.subTest(quote=quote):
                ep = episode()
                self.add(ep, "op", [plan("Surgery", quote, **fields)])
                self.assert_planned(ep, "Surgery", headline)

    def test_a_later_update_that_plans_it_again_is_planned(self):
        ep = episode()
        self.add(ep, "cancel", [plan("Surgery", CANCELLED)])
        self.add(ep, "again", [plan("Surgery", "Surgery is now planned for Friday", when_text="Friday")],
                 at="2026-10-21T15:00:00+01:00")
        view, out = self.surfaces(ep)
        self.assertEqual(len(view["next"]), 1)
        self.assertIn("Fri 23 Oct", view["next"][0]["text"])
        self.assertIn("Waiting for surgery", visible(out["hero"]))
        self.assertIn(T.esc(CANCELLED), out["timeline"])   # the earlier cancellation keeps its own words


class TestDisplayHeadline(DisplayCase):
    """display_headline: what the page's 'Timeline updated: ...' message says about a new update."""

    def test_a_plan_that_will_not_happen_is_told_in_its_own_words(self):
        for what, quote, fields in (("Operation", NOT_OPERATING, {"when_text": "tomorrow morning"}),
                                    ("MRI", "MRI is not required", {}),
                                    ("Surgery", CANCELLED, {})):
            with self.subTest(quote=quote):
                ep = episode()
                entry = self.add(ep, "op", [plan(what, quote, **fields)])
                self.assertIn(f"{what} planned", entry["headline"])   # the core's own headline is unchanged
                self.assertEqual(T.display_headline(entry), quote)
                cards = re.findall(r'data-headline="([^"]*)"', T.timeline_html(ep, "anna", TZ))
                if what != "MRI":   # a test is shown in the tests topic, with its quote
                    self.assertEqual([html.unescape(card) for card in cards], [quote])

    def test_a_plan_that_stands_keeps_the_core_headline(self):
        for quote, fields in ((REBOOKED, {"when_text": "Friday"}),
                              ("Surgery is planned for tomorrow morning", {"when_text": "tomorrow morning"}),
                              ("Surgery has not been cancelled and goes ahead on Friday", {"when_text": "Friday"})):
            with self.subTest(quote=quote):
                ep = episode()
                entry = self.add(ep, "op", [plan("Surgery", quote, **fields)])
                self.assertTrue(entry["headline"].startswith("Surgery planned"))
                self.assertEqual(T.display_headline(entry), entry["headline"])

    def test_an_update_without_facts_keeps_its_headline(self):
        ep = episode()
        entry = ep.add_update({"update_id": "n", "at": AT, "kind": "note", "author": "anna", "text": "Thinking of you."},
                              facts=[])
        self.assertEqual(T.display_headline(entry), entry["headline"])


if __name__ == "__main__":
    unittest.main(verbosity=1)
