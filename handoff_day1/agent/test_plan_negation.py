#!/usr/bin/env python3
"""A plan the care team says will NOT happen is not shown as the plan (episode.grounding_problem; metamorphic
MR1/episode/plan-negated, confirmed live on u07 and u07c: "Going home is not planned for Saturday morning" was shown as
"Going home moved: Fri 23 Oct -> Sat 24 Oct morning"). For going home and follow-ups; a negation inside a condition, a
time bound ('not until Friday'), a cancellation and a planned procedure (the timeline reads a test's negation from its
quote) keep the fact. Stdlib only:
  python test_plan_negation.py
"""
from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from episode import Episode, grounding_problem, load_scenario  # noqa: E402

STORY = load_scenario(HERE.parent / "care_cases" / "episode_hip_fracture.json")
AT = "2026-10-21T10:00:00+01:00"   # a Wednesday: Friday is 23 Oct, Monday 26 Oct
NOT_PLANNED = "not planned"


def fact(typ: str, quote: str, **fields) -> dict:
    return {"type": typ, "quote": quote, **fields}


def home(quote: str, when_text: str = "Friday", **fields) -> dict:
    return fact("expected_discharge", quote, when_text=when_text, **fields)


class NegatedPlanIsRejected(unittest.TestCase):
    """The quote's own clause says the plan does not stand: the fact is refused with a reason."""

    def test_negated_plans_are_refused(self):
        rows = [("She will not go home on Friday.", home("She will not go home on Friday")),
                ("She won't be discharged on Friday.", home("She won't be discharged on Friday")),
                ("She is not going home on Friday.", home("She is not going home on Friday")),
                ("She isn't going home on Friday.", home("She isn't going home on Friday")),
                ("She cannot go home on Friday, the wound is still leaking.", home("She cannot go home on Friday")),
                ("On Friday, she will not go home.", home("On Friday, she will not go home")),
                ("This Friday, she will not go home.", home("This Friday, she will not go home")),
                ("She is no longer going home on Friday.", home("She is no longer going home on Friday")),
                ("Going home on Friday is not planned.", home("Going home on Friday")),   # the negation after the quote
                ("She stays with us tonight and does not go home tomorrow morning, Saturday.",
                 home("does not go home tomorrow morning, Saturday", "tomorrow morning, Saturday")),
                ("The fracture clinic will not see her next week.",
                 fact("follow_up", "The fracture clinic will not see her next week", what="Fracture clinic appointment",
                      where="fracture clinic", when_text="next week")),
                ("The district nurse won't visit her at home on Tuesday.",
                 fact("follow_up", "The district nurse won't visit her at home on Tuesday", what="District nurse visit",
                      where="at home", when_text="Tuesday"))]
        for text, f in rows:
            with self.subTest(text=text):
                why = grounding_problem(f, text, AT)
                self.assertIsNotNone(why, "a plan the quote says will not happen was accepted")
                self.assertIn(NOT_PLANNED, why)

    def test_the_live_u07_negflip_does_not_move_going_home(self):
        # the model's facts on the negated u07 (release/benchmarks/metamorphic_20261017T233944Z/live_records.jsonl)
        ep = Episode({**STORY, "updates": []})
        for u in STORY["updates"][:6]:   # u01 .. u06: going home is Friday 23 Oct, if she is walking safely
            ep.add_update(copy.deepcopy(u))
        friday = ep.slots["expected_discharge"]["fact"]["when"]
        u07 = copy.deepcopy(next(u for u in STORY["updates"] if u["update_id"] == "u07"))
        u07["text"] = u07["text"].replace("Going home is now planned for Saturday morning.",
                                          "Going home is not planned for Saturday morning.")
        self.assertIn("Going home is not planned for Saturday morning.", u07["text"])
        e = ep.add_update(u07, facts=[{"type": "expected_discharge", "quote": "Going home is not planned for Saturday morning",
                                       "condition": "not planned", "when": "2026-10-24", "when_text": "Saturday morning"}])
        self.assertEqual([r["fact"]["type"] for r in e["rejected"]], ["expected_discharge"])
        self.assertIn(NOT_PLANNED, e["rejected"][0]["reason"])
        self.assertEqual(ep.slots["expected_discharge"]["fact"]["when"], friday)
        self.assertNotIn("Going home moved", e["headline"])
        self.assertNotIn("Sat 24 Oct", e["headline"])

    def test_the_live_u07c_negflip_is_refused(self):
        text = ("I checked with Mr Okafor's team. She was dizzy again after lunch, so she stays with us tonight and does not "
                "go home tomorrow morning, Saturday.")
        f = {"type": "expected_discharge", "quote": "does not go home tomorrow morning, Saturday", "condition": "does not go home",
             "when": "2026-10-24", "when_text": "tomorrow morning, Saturday"}
        self.assertIn(NOT_PLANNED, grounding_problem(f, text, "2026-10-23T14:30:00+01:00") or "")

    def test_a_quote_said_once_negated_and_once_not_is_kept(self):
        # as for the existing negation rule: one occurrence that is not negated grounds the fact
        text = "Going home on Friday is not planned. Going home on Friday is planned now, the consultant says."
        self.assertIsNotNone(grounding_problem(home("Going home on Friday"), "Going home on Friday is not planned.", AT))
        self.assertIsNone(grounding_problem(home("Going home on Friday"), text, AT))


class PlanThatStandsIsKept(unittest.TestCase):
    """No false block: a negation that does not govern the plan leaves the fact as it was."""

    def test_positive_plans_are_kept(self):
        rows = [("She will go home on Friday.", home("She will go home on Friday")),
                ("The operation is planned for Monday.",
                 fact("procedure_planned", "The operation is planned for Monday", what="Operation", when_text="Monday")),
                ("The fracture clinic will see her next week.",
                 fact("follow_up", "The fracture clinic will see her next week", what="Fracture clinic appointment",
                      where="fracture clinic", when_text="next week"))]
        for text, f in rows:
            with self.subTest(text=text):
                self.assertIsNone(grounding_problem(f, text, AT))

    def test_a_negation_inside_a_condition_does_not_reverse_the_plan(self):
        rows = [("If she does not have a fever she can go home on Friday.", "If she does not have a fever she can go home on Friday",
                 "If she does not have a fever"),
                ("If she does not have a fever, she can go home on Friday.", "If she does not have a fever, she can go home on Friday",
                 "If she does not have a fever"),
                ("She can go home on Friday unless she is not eating.", "She can go home on Friday unless she is not eating",
                 "unless she is not eating"),
                ("She can go home on Friday as long as she is not dizzy.", "She can go home on Friday as long as she is not dizzy",
                 "as long as she is not dizzy"),
                ("She can go home on Friday once she no longer needs oxygen.",
                 "She can go home on Friday once she no longer needs oxygen", "once she no longer needs oxygen")]
        for text, quote, condition in rows:
            with self.subTest(text=text):
                self.assertIsNone(grounding_problem(home(quote, condition=condition), text, AT))

    def test_a_time_bound_is_not_a_negated_plan(self):
        # 'not until Friday', 'not before Monday', 'no earlier than Friday' bound the date; the fact keeps the date said
        # (as before this change); refusing them would hide a date the care team gave
        rows = [("She will not go home until Friday.", home("She will not go home until Friday")),
                ("She won't be discharged before Friday.", home("She won't be discharged before Friday")),
                ("She can go home no earlier than Friday.", home("She can go home no earlier than Friday")),
                ("She can go home on Friday, not before.", home("She can go home on Friday, not before")),
                ("The operation will not be before Monday.",
                 fact("procedure_planned", "The operation will not be before Monday", what="Operation", when_text="Monday"))]
        for text, f in rows:
            with self.subTest(text=text):
                self.assertIsNone(grounding_problem(f, text, AT))

    def test_a_negation_about_something_else_is_not_the_plan(self):
        rows = [("She is not in pain any more and can go home on Friday.",
                 home("She is not in pain any more and can go home on Friday")),
                ("She has not eaten since midnight, so the operation is this afternoon.",
                 fact("procedure_planned", "the operation is this afternoon", what="Operation", when_text="this afternoon")),
                ("Don't worry, she will go home on Friday.", home("Don't worry, she will go home on Friday")),
                ("She will not go home on Friday; going home is now planned for Saturday morning.",
                 home("going home is now planned for Saturday morning", "Saturday morning")),
                ("She is no longer going home on Friday; she will go home on Saturday.",
                 home("She is no longer going home on Friday; she will go home on Saturday", "Saturday")),
                ("She can go home on Friday, fasting is not required.", home("She can go home on Friday, fasting is not required")),
                ("She can go home tomorrow morning, Saturday, she does not need the drip any more.",
                 home("She can go home tomorrow morning, Saturday, she does not need the drip any more",
                      "tomorrow morning, Saturday")),
                ("The fracture clinic will see her next week, she doesn't need to bring anything.",
                 fact("follow_up", "The fracture clinic will see her next week, she doesn't need to bring anything",
                      what="Fracture clinic appointment", where="fracture clinic", when_text="next week"))]
        for text, f in rows:
            with self.subTest(text=text):
                self.assertIsNone(grounding_problem(f, text, AT))

    def test_a_negated_procedure_stays_with_the_timelines_test_reading(self):
        # test_timeline_html (test_negative_instructions_do_not_cancel_a_test_but_explicit_plan_changes_do): the timeline
        # keeps these procedures and reads the negation from the quote (not upcoming), so grounding keeps them
        for quote in ("MRI is not required", "MRI is no longer booked", "MRI is planned for 18 October 2026, fasting is not required",
                      "MRI is planned for 18 October 2026 and has not been cancelled"):
            with self.subTest(quote=quote):
                self.assertIsNone(grounding_problem(fact("procedure_planned", quote, what="MRI"), quote, "2026-10-17T10:00:00+01:00"))

    def test_cancellations_stay_with_the_timelines_cancellation_reading(self):
        # test_review_fixes_s1 (RebookedTestStaysNext, CancelledTestNotNext): the procedure is kept and the timeline reads
        # the cancellation from its quote, a negated cancellation included; 'no contrast' and 'nothing to eat' are not
        # the procedure's negation
        for quote in ("The MRI has not been cancelled.", "Do not cancel the MRI.",
                      "MRI was cancelled and has not been rebooked for 18 October 2026.",
                      "MRI was rebooked for 18 October 2026 and has not since been cancelled.",
                      "MRI was postponed and has not been rescheduled.",
                      "MRI on 18 October 2026: no contrast, and nothing to eat before the MRI."):
            with self.subTest(quote=quote):
                self.assertIsNone(grounding_problem(fact("procedure_planned", quote, what="MRI"), quote,
                                                    "2026-10-17T10:00:00+01:00"))

    def test_the_story_replays_without_a_rejection(self):
        ep = Episode({**STORY, "updates": []})
        for u in STORY["updates"]:
            e = ep.add_update(copy.deepcopy(u))
            self.assertEqual(e["rejected"], [], u["update_id"])


if __name__ == "__main__":
    unittest.main()
