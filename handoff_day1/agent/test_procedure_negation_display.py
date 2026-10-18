#!/usr/bin/env python3
"""A care-team quote that says a procedure will NOT happen is kept as procedure_planned by design (the timeline reads the
negation from the quote: test_timeline_html's 'MRI is not required'), so every surface must read it the same way: the
timeline card, Right now and What's next show the source's own words, never 'Operation planned: ...', 'Waiting for ...'
or a 'Planned' label. A negation in another clause, a re-plan and a negated cancellation keep the plan; the core
procedure record is not changed. Stdlib only:
  python agent/test_procedure_negation_display.py
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


class TestNegatedProcedureDisplay(unittest.TestCase):
    def add(self, ep: Episode, uid: str, facts: list[dict], text: str | None = None) -> dict:
        entry = ep.add_update({"update_id": uid, "at": AT, "kind": "recording", "speaker": "Doctor", "author": "anna",
                               "text": text or ". ".join(f["quote"] for f in facts) + "."}, facts=facts)
        self.assertEqual(entry["rejected"], [])
        return entry

    def surfaces(self, ep: Episode) -> tuple[dict, dict]:
        view = T.presentation_model(ep, "anna", TZ)
        state = ep.status(TZ)
        return view, {"timeline": T.timeline_html(ep, "anna", TZ, presentation=view),
                      "hero": T.hero_html(ep, state, TZ, ep.members["anna"], presentation=view),
                      "side": T.side_html(ep, state, TZ, "anna", presentation=view)}

    def assert_not_planned(self, ep: Episode, quote: str, what: str, surfaces=("timeline", "hero")):
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
        for name in surfaces:
            self.assertIn(T.esc(quote), out[name])   # the source's own words carry the negation
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

    def test_a_negated_operation_is_not_shown_as_planned_anywhere(self):
        ep = episode()
        self.add(ep, "op", [plan("Operation", NOT_OPERATING, when_text="tomorrow morning")])
        self.assert_not_planned(ep, NOT_OPERATING, "Operation")
        card = T.timeline_html(ep, "anna", TZ)
        self.assertIn(f'data-headline="{T.esc(NOT_OPERATING)}"', card)   # the key event keeps its stated date and source
        self.assertIn("Thursday 22 Oct 2026", card)
        self.assertIn('class="cr-ev cr-key"', card)

    def test_other_negated_wordings_and_a_missing_when_text(self):
        for what, quote, fields in (("Operation", NOT_OPERATING, {}),
                                    ("Surgery", "Surgery is not required", {}),
                                    ("Surgery", "No surgery is planned", {}),
                                    ("Surgery", "Surgery is no longer booked", {}),
                                    ("Surgery", "She will not have surgery on Friday", {"when_text": "Friday"})):
            with self.subTest(quote=quote):
                ep = episode()
                self.add(ep, "op", [plan(what, quote, **fields)])
                self.assert_not_planned(ep, quote, what)

    def test_a_negated_mri_is_not_upcoming_and_keeps_its_quote(self):
        ep = episode()
        self.add(ep, "mri", [plan("MRI", "MRI is not required")])
        self.assert_not_planned(ep, "MRI is not required", "MRI", surfaces=("timeline",))   # Right now has no event card
        view, out = self.surfaces(ep)
        self.assertFalse(view["test_topics"][0]["upcoming"])
        self.assertIn("Tests and examinations mentioned", visible(out["hero"]))   # the existing neutral Right now

    def test_a_positive_operation_stays_planned(self):
        ep = episode()
        self.add(ep, "op", [plan("Surgery", "Surgery is planned for tomorrow morning", when_text="tomorrow morning")])
        self.assert_planned(ep, "Surgery", "Surgery planned: Thu 22 Oct morning")

    def test_a_negation_in_another_clause_a_replan_and_a_negated_cancellation_keep_the_plan(self):
        for quote, fields, headline in (
                ("Surgery is planned for tomorrow morning, fasting is not required", {"when_text": "tomorrow morning"},
                 "Surgery planned: Thu 22 Oct morning"),
                ("Surgery is planned for tomorrow morning, fasting is not required", {}, "Surgery planned: Thu 22 Oct morning"),
                ("Surgery is planned for tomorrow morning; she should not eat beforehand", {"when_text": "tomorrow morning"},
                 "Surgery planned: Thu 22 Oct morning"),
                ("Surgery is not needed today, it is now planned for Friday", {"when_text": "Friday"},
                 "Surgery planned: Friday"),   # the core leaves two stated days as written
                ("Surgery has not been cancelled and goes ahead on Friday", {"when_text": "Friday"},
                 "Surgery planned: Fri 23 Oct"),
                ("Surgery is not until Friday", {"when_text": "Friday"}, "Surgery planned: Fri 23 Oct")):
            with self.subTest(quote=quote, fields=fields):
                ep = episode()
                self.add(ep, "op", [plan("Surgery", quote, **fields)])
                self.assert_planned(ep, "Surgery", headline)

    def test_an_mri_negation_in_another_clause_stays_upcoming_on_every_surface(self):
        ep = episode()
        self.add(ep, "mri", [plan("MRI", "MRI is planned for 23 October 2026, fasting is not required")])
        view, out = self.surfaces(ep)
        self.assertTrue(view["test_topics"][0]["upcoming"])
        for name in ("hero", "side"):
            self.assertIn("Tests and examinations · 1 source", visible(out[name]))

    def test_a_negated_plan_does_not_hide_another_planned_procedure(self):
        ep = episode()
        self.add(ep, "op", [plan("Operation", NOT_OPERATING, when_text="tomorrow morning")])
        self.add(ep, "physio", [plan("Physiotherapy assessment", "Physiotherapy assessment is planned for Friday",
                                     when_text="Friday")])
        view, out = self.surfaces(ep)
        self.assertEqual([item["text"] for item in view["next"]], ["Physiotherapy assessment planned: Fri 23 Oct"])
        hero, side = visible(out["hero"]), visible(out["side"])
        self.assertIn("Waiting for physiotherapy assessment", hero)
        self.assertNotIn("Operation planned", hero + side + visible(out["timeline"]))
        self.assertIn("Physiotherapy assessment planned: Fri 23 Oct", side)


if __name__ == "__main__":
    unittest.main(verbosity=1)
