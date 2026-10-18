#!/usr/bin/env python3
"""Tests for the family timeline (episode.py): replay of the demo story, grounding, family reports vs care-team sources,
supersession, time zones, read state, and the live-model extractor with a stub model. Stdlib only:
  python test_episode.py
"""
from __future__ import annotations

import ast
import base64
import copy
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from episode import Episode, grounding_problem, llm_extractor, load_scenario, photo_reader  # noqa: E402

TWO_ANSWERS = ("u07b", "u07c")   # the story's two-different-answers pair; the older tests replay the story without it


def without_two_answers(scenario: dict) -> dict:
    return {**scenario, "updates": [u for u in scenario["updates"] if u["update_id"] not in TWO_ANSWERS]}


FULL = load_scenario(HERE.parent / "care_cases" / "episode_hip_fracture.json")
SCENARIO = without_two_answers(FULL)
HEADLINES = [
    "At St Mary's Hospital, A&E",
    "Admitted: St Mary's Hospital, Orthopaedic ward 5B, bed 12",
    "Visiting hours 11:00 - 13:00 and 17:00 - 20:00; maximum 2 visitors per bed",
    "David: Flying in from Toronto, landing Wednesday morning; will do evening visits from Wednesday",
    "Half hip replacement done",
    "Stood up with the walking frame at physiotherapy",
    "Going home moved: Fri 23 Oct -> Sat 24 Oct morning",
    "Medication list updated: 3 new, 1 stopped, 1 continued or changed",
    "Discharged from hospital",
    "Home and settled",
]
PHASES = ["In the emergency department"] + ["Waiting for hip surgery"] * 3 + ["Current patient status needs confirmation"] * 4 + \
         ["Home after hospital"] * 2


def replayed(upto: int | None = None) -> Episode:
    ep = Episode(SCENARIO)
    for u in SCENARIO["updates"][:upto]:
        ep.add_update(u)
    return ep


class TestReplay(unittest.TestCase):
    def test_story(self):
        ep = Episode(SCENARIO)
        for u, headline, phase in zip(SCENARIO["updates"], HEADLINES, PHASES):
            e = ep.add_update(u)
            self.assertEqual(e["rejected"], [], u["update_id"])
            self.assertEqual(e["headline"], headline)
            self.assertEqual(ep.phase(), phase, u["update_id"])
        self.assertEqual([e["headline"] for e in ep.timeline()], HEADLINES[::-1])   # newest first

    def test_final_status(self):
        ep = replayed()
        s = ep.status(tz="Europe/London", now=SCENARIO["updates"][-1]["at"])
        self.assertEqual(s["location"]["text"], "at home")
        self.assertEqual(s['phase'], 'Home after hospital')
        # This demo's plan and undated admission/discharge are separate source
        # assertions. Receipt order cannot prove that the plan was fulfilled;
        # retain it after the three unchanged, explicitly scheduled follow-ups.
        self.assertEqual(s["next"], ["District nurse wound check: Tue 27 Oct, at home",
                                     "Staples removed at the GP practice: Thu 05 Nov",
                                     "Fracture clinic appointment: Mon 30 Nov 10:30",
                                     "Discharge plan: confirm which admission — Expected to go home: Sat 24 Oct morning"])
        relation = ep.discharge_plan_relation(ep.slots['expected_discharge'])
        self.assertEqual((relation['status'], relation['supporting_sources']), ('unresolved', []))
        self.assertIsNone(s['discharged']['when'])
        self.assertIsNone(s['discharged']['event_time']['when'])
        self.assertEqual(ep.slots['expected_discharge']['event_time']['when'], '2026-10-24')
        self.assertEqual(ep.slots['expected_discharge']['event_time']['precision'], 'part_of_day')
        active = [m["text"] for m in s["medicines"] if m["active"]]
        self.assertEqual(len(active), 4)
        self.assertIn("Stopped: Ibuprofen", [m["text"] for m in s["medicines"] if not m["active"]])
        self.assertEqual(s["procedures"], [{"what": "Hip surgery", "status": "done"}])   # done = the planned one
        self.assertTrue(s["warning_signs"])

    def test_status_while_in_hospital(self):
        s = replayed(3).status(tz="Europe/London", now=SCENARIO["updates"][2]["at"])
        self.assertEqual(s["location"]["text"], "St Mary's Hospital, Orthopaedic ward 5B, bed 12")
        self.assertFalse(s["location"]["unconfirmed"])
        self.assertEqual(s["next"], ["Hip surgery planned: Tue 20 Oct 09:00"])
        self.assertIn("11:00 - 13:00", s["visiting"]["text"])
        self.assertEqual(s["contacts"], ["Ward phone: 020 7946 0123"])

    def test_now_hides_past_events(self):
        ep = replayed(5)
        self.assertEqual(ep.status(now="2026-10-21T08:00:00+01:00")["next"],
                         ["Expected to go home: Fri 23 Oct (if she is walking safely with the frame)"])
        self.assertEqual(ep.status(now="2026-10-24T00:00:00+01:00")["next"], [])


class TestMerge(unittest.TestCase):
    def test_family_report_is_unconfirmed_until_care_team(self):
        ep = replayed(1)
        self.assertTrue(ep.status()["location"]["unconfirmed"])
        e = ep.add_update(SCENARIO["updates"][1])
        self.assertFalse(ep.status()["location"]["unconfirmed"])
        loc = next(ln for ln in e["lines"] if ln["type"] == "location")
        self.assertEqual(loc["changed_from"], "St Mary's Hospital, A&E")

    def test_family_report_never_overrides_care_team(self):
        ep = replayed(2)
        note = {"update_id": "x1", "at": "2026-10-19T12:00:00+01:00", "kind": "note", "author": "david",
                "text": "I heard she was moved to Ward 7 upstairs.",
                "recorded_extraction": [{"type": "location", "unit": "Ward 7", "quote": "she was moved to Ward 7 upstairs"}]}
        e = ep.add_update(note)
        s = ep.status()
        self.assertEqual(s["location"]["text"], "St Mary's Hospital, Orthopaedic ward 5B, bed 12")
        self.assertIn("the care team said otherwise", e["lines"][0]["text"])
        self.assertEqual((e["headline"], e["headline_flag"]), ("Family reports: At St Mary's Hospital, Ward 7", "contradicted"))
        self.assertEqual(s["last_update"]["flag"], "contradicted")

    def test_supersession_keeps_history(self):
        ep = replayed(7)
        slot = ep.slots["expected_discharge"]
        self.assertEqual(slot["fact"]["when"], "2026-10-24")
        self.assertEqual([h["fact"]["when"] for h in slot["history"]], ["2026-10-23"])
        s = ep.status()["expected_discharge"]
        self.assertEqual((s["short"], s["was"]), ("Sat 24 Oct morning", "Fri 23 Oct"))
        self.assertIsNone(ep.status()["doctor_in_charge"]["was"])

    def test_medicine_change_and_stop(self):
        ep = replayed(8)
        upd = {"update_id": "x2", "at": "2026-10-26T09:00:00+00:00", "kind": "photo", "author": "anna", "photo_of": "GP letter",
               "text": "Paracetamol 500 mg four times a day as needed for pain. Stop Lansoprazole now.",
               "recorded_extraction": [
                   {"type": "medication", "name": "Paracetamol", "dose": "500 mg", "frequency": "four times a day as needed for pain",
                    "status": "change", "quote": "Paracetamol 500 mg four times a day as needed for pain"},
                   {"type": "medication", "name": "Lansoprazole", "status": "stop", "quote": "Stop Lansoprazole now"}]}
        e = ep.add_update(upd)
        para = next(ln for ln in e["lines"] if ln["fact"]["name"] == "Paracetamol")
        self.assertEqual(para["changed_from"], "Paracetamol 1 g four times a day as needed for pain")
        self.assertEqual(e["headline"], "Medication list updated: 0 new, 1 stopped, 1 continued or changed")
        self.assertNotIn("Lansoprazole", " ".join(m["text"] for m in ep.status()["medicines"] if m["active"]))



class TestTwoAnswers(unittest.TestCase):
    """Another member of the care team gives a different answer, without saying the plan changed: both stay on show and
    the question goes to the doctor's list, until a later care-team statement settles it."""

    def full(self, upto: str | None = None) -> Episode:
        ep = Episode(FULL)
        for u in FULL["updates"]:
            ep.add_update(u)
            if u["update_id"] == upto:
                break
        return ep

    def test_the_story_raises_and_settles_one_pair(self):
        ep = self.full("u07b")
        s = ep.status(tz="Europe/London")
        self.assertEqual(s["expected_discharge"]["short"], "Fri 23 Oct")
        self.assertEqual(s["expected_discharge"]["other"], "Sat 24 Oct morning")
        self.assertIsNone(s["expected_discharge"]["was"])   # not a change: two answers
        [two] = s["two_answers"]
        self.assertEqual([a["who"] for a in two["answers"]], ["Ward nurse", "Mr Okafor, consultant"])
        self.assertIn("Going home is now planned for Saturday morning", two["answers"][0]["quote"])
        last = ep.timeline("anna")[0]
        self.assertEqual(last["headline"], "Two different answers about going home: Sat 24 Oct morning or Fri 23 Oct?")
        self.assertEqual(last["headline_flag"], "two_answers")
        [q] = ep.questions
        self.assertEqual((q["status"], q["auto"], q["askers"]), ("open", "two_answers", []))
        self.assertIn("Which is right?", q["text"])
        self.assertTrue(any("two different answers" in n for n in s["next"]))
        ep.add_update(next(u for u in FULL["updates"] if u["update_id"] == "u07c"))
        s = ep.status(tz="Europe/London")
        self.assertEqual((s["expected_discharge"]["short"], s["two_answers"]), ("Sat 24 Oct morning", []))
        self.assertEqual((q["status"], q["answered_by"]), ("answered", "u07c"))
        self.assertEqual(ep.timeline("anna")[0]["headline"], "Settled, going home: Sat 24 Oct morning")

    def plan(self, ep, uid, at, speaker, text, when_text, when, kind="recording"):
        q = text.rstrip(".")
        return ep.add_update({"update_id": uid, "at": at, "kind": kind, "author": "anna", "speaker": speaker, "text": text,
                              "recorded_extraction": [{"type": "expected_discharge", "when_text": when_text, "when": when, "quote": q}]})

    def base(self):
        ep = Episode(SCENARIO)
        self.plan(ep, "p1", "2026-10-21T10:00:00+01:00", "Ward nurse", "She can go home on Friday.", "Friday", "2026-10-23")
        return ep

    def test_a_change_said_out_loud_is_an_update(self):
        ep = self.base()
        e = self.plan(ep, "p2", "2026-10-21T15:00:00+01:00", "Mr Okafor", "Going home is now Saturday.", "Saturday", "2026-10-24")
        self.assertEqual((ep.status()["two_answers"], e["headline_flag"], ep.questions), ([], None, []))

    def test_the_same_speaker_correcting_themself_is_an_update(self):
        ep = self.base()
        self.plan(ep, "p2", "2026-10-21T15:00:00+01:00", "Ward nurse", "She can go home on Saturday.", "Saturday", "2026-10-24")
        self.assertEqual(ep.status()["two_answers"], [])

    def test_answers_days_apart_are_an_update(self):
        ep = self.base()
        self.plan(ep, "p2", "2026-10-23T12:00:00+01:00", "Mr Okafor", "She can go home on Saturday.", "Saturday", "2026-10-24")
        self.assertEqual(ep.status()["two_answers"], [])

    def test_a_family_note_never_makes_two_answers(self):
        ep = self.base()
        self.plan(ep, "p2", "2026-10-21T15:00:00+01:00", None, "She can go home on Saturday.", "Saturday", "2026-10-24", kind="note")
        self.assertEqual((ep.status()["two_answers"], ep.questions), ([], []))

    def test_the_paper_and_the_nurse_disagree_about_a_medicine(self):
        ep = Episode(SCENARIO)
        ep.add_update({"update_id": "m1", "at": "2026-10-24T10:30:00+01:00", "kind": "photo", "author": "anna",
                       "photo_of": "Discharge medication list", "text": "STOP taking Ibuprofen.",
                       "recorded_extraction": [{"type": "medication", "name": "Ibuprofen", "status": "stop", "quote": "STOP taking Ibuprofen"}]})
        e = ep.add_update({"update_id": "m2", "at": "2026-10-24T11:15:00+01:00", "kind": "recording", "author": "anna",
                           "speaker": "Discharge nurse", "text": "She can keep taking her Ibuprofen 400 mg three times a day.",
                           "recorded_extraction": [{"type": "medication", "name": "Ibuprofen", "dose": "400 mg", "frequency": "three times a day",
                                                    "status": "continue", "quote": "She can keep taking her Ibuprofen 400 mg three times a day"}]})
        self.assertEqual(e["headline"], "Two different answers about Ibuprofen: stop it or take it 400 mg three times a day?")
        [q] = ep.questions
        self.assertEqual(q["text"], "Ibuprofen: stop it (the discharge medication list) or take it 400 mg three times a day "
                                    "(Discharge nurse)? Which is right?")


class TestTesterFindings(unittest.TestCase):
    """Cases a tester entered by hand (2026-10-16)."""

    @staticmethod
    def upto(uid):
        ep = Episode(FULL)
        for u in FULL["updates"]:
            ep.add_update(u)
            if u["update_id"] == uid:
                return ep

    @staticmethod
    def rec(uid, at, speaker, text, when, when_text):
        return {"update_id": uid, "at": at, "kind": "recording", "author": "anna", "speaker": speaker, "text": text,
                "recorded_extraction": [{"type": "expected_discharge", "when_text": when_text, "when": when, "quote": text.rstrip(".")}]}

    def test_a_summary_never_drops_not(self):
        ep = replayed(5)
        e = ep.add_update(upd("n1", "2026-10-21T09:00:00+01:00", "recording", "She must not walk without a nurse.",
                              [{"type": "instruction", "what": "She may walk alone.", "quote": "She must not walk without a nurse"}],
                              speaker="Ward nurse"))
        self.assertEqual(e["rejected"], [])
        self.assertEqual(ep.status()["instructions"][-1]["text"], "She must not walk without a nurse")   # the original words
        self.assertIsNotNone(grounding_problem({"type": "instruction", "what": "She may walk alone.", "quote": "She must not walk without a nurse"},
                                               "She must not walk without a nurse.", "2026-10-21T09:00:00+01:00"))
        # Negation can also be moved to the wrong action while the 'not' token remains.
        e = ep.add_update(upd("n2", "2026-10-21T09:01:00+01:00", "recording", "She must not walk without a nurse.",
                              [{"type": "instruction", "what": "She does not need a nurse to walk.",
                                "quote": "She must not walk without a nurse"}], speaker="Ward nurse"))
        self.assertEqual(e["facts"][0]["what"], "She must not walk without a nurse")

    def test_a_plan_with_a_condition_keeps_it(self):
        why = grounding_problem({"type": "expected_discharge", "when_text": "Friday", "when": "2026-10-23",
                                 "quote": "If she is walking safely with the frame, she could go home on Friday"},
                                "If she is walking safely with the frame, she could go home on Friday.", "2026-10-20T13:40:00+01:00")
        self.assertIn("condition", why)

    def test_same_day_different_times_are_two_answers(self):
        ep = replayed(6)
        ep.add_update(self.rec("a1", "2026-10-22T09:00:00+01:00", "Mr Okafor, consultant", "She goes home on Friday at 10:00.", "2026-10-23T10:00", "Friday at 10:00"))
        e = ep.add_update(self.rec("a2", "2026-10-22T11:00:00+01:00", "Ward nurse", "She goes home on Friday at 15:00.", "2026-10-23T15:00", "Friday at 15:00"))
        self.assertTrue(e["headline"].startswith("Two different answers about going home"))
        e = ep.add_update(self.rec("a3", "2026-10-22T12:00:00+01:00", "Physiotherapist", "She goes home on Friday as planned.", "2026-10-23", "Friday"))
        self.assertFalse(e["headline"].startswith("Two different answers"))   # a day without a time does not disagree

    def test_said_again_does_not_settle(self):
        ep = self.upto("u07b")
        e = ep.add_update(self.rec("a3", "2026-10-23T10:00:00+01:00", "Ward nurse", "Going home is planned for Saturday morning.", "2026-10-24", "Saturday morning"))
        self.assertEqual(e["headline"], "Said again, still two different answers about going home: Sat 24 Oct morning")
        self.assertEqual(len(ep.two_answers()), 1)
        self.assertEqual([q["status"] for q in ep.questions if q.get("auto")], ["open"])
        self.assertEqual(ep.status()["expected_discharge"]["other"], "Fri 23 Oct")
        e = ep.add_update(next(u for u in FULL["updates"] if u["update_id"] == "u07c"))   # "I checked with Mr Okafor's team"
        self.assertEqual(ep.two_answers(), [])
        self.assertEqual([q["status"] for q in ep.questions if q.get("auto")], ["answered"])

    def test_the_one_who_said_otherwise_settles_it(self):
        ep = self.upto("u07b")
        ep.add_update(self.rec("a4", "2026-10-23T11:00:00+01:00", "Mr Okafor, consultant", "She goes home on Saturday morning.", "2026-10-24", "Saturday morning"))
        self.assertEqual(ep.two_answers(), [])

    def test_family_confirms_which_is_right(self):
        ep = self.upto("u07b")
        qid = ep.two_answers()[0]["qid"]
        with self.assertRaises(ValueError):
            ep.confirm_answer(qid, "u05", "anna")   # not one of the two
        q = ep.confirm_answer(qid, "u07", "anna")   # the nurse's Saturday, the earlier answer
        self.assertEqual((q["status"], q["marked_by"], q["confirmed"]), ("answered", "anna", "Sat 24 Oct morning"))
        s = ep.status()["expected_discharge"]
        self.assertEqual((s["short"], s["other"], s["confirmed_by"]), ("Sat 24 Oct morning", None, "Anna"))
        self.assertEqual(ep.two_answers(), [])

    def test_unconfirmed_or_future_confirmation_stays_open(self):
        for ending in ("This has not been confirmed.", "We still need to confirm this.",
                       "This will be confirmed tomorrow.", "Has this been confirmed?"):
            with self.subTest(ending=ending):
                ep = self.upto("u07b")
                text = "Going home is planned for Saturday morning. " + ending
                ep.add_update(self.rec("a5", "2026-10-23T10:00:00+01:00", "Ward nurse", text,
                                       "2026-10-24", "Saturday morning"))
                self.assertEqual(len(ep.two_answers()), 1)
                self.assertEqual(ep.questions[0]["status"], "open")

    def test_confirmation_of_another_subject_does_not_settle(self):
        ep = self.upto("u07b")
        u = self.rec("a5", "2026-10-23T10:00:00+01:00", "Ward nurse",
                     "The physiotherapy appointment is confirmed. Going home is planned for Saturday morning.",
                     "2026-10-24", "Saturday morning")
        u["recorded_extraction"][0]["quote"] = "Going home is planned for Saturday morning"
        ep.add_update(u)
        self.assertEqual(len(ep.two_answers()), 1)

    def test_a_date_alone_preserves_both_disputed_clock_times(self):
        for speaker in ("Physiotherapist", "Mr Okafor, consultant", "Ward nurse"):
            with self.subTest(speaker=speaker):
                ep = replayed(6)
                ep.add_update(self.rec("a1", "2026-10-22T09:00:00+01:00", "Mr Okafor, consultant",
                                      "She goes home on Friday at 10:00.", "2026-10-23T10:00", "Friday at 10:00"))
                ep.add_update(self.rec("a2", "2026-10-22T11:00:00+01:00", "Ward nurse",
                                      "She goes home on Friday at 15:00.", "2026-10-23T15:00", "Friday at 15:00"))
                before = ep.two_answers()[0]
                ep.add_update(self.rec("a3", "2026-10-22T12:00:00+01:00", speaker,
                                      "She goes home on Friday as planned.", "2026-10-23", "Friday"))
                self.assertEqual(ep.two_answers()[0], before)
                self.assertEqual(ep.questions[0]["status"], "open")


class TestPlans(unittest.TestCase):
    PLAN = "I'll pick her up on Friday afternoon."

    def plan(self, ep, uid, at, who="joy"):
        return ep.add_update({"update_id": uid, "at": at, "kind": "note", "topic": "plan", "author": who, "text": self.PLAN,
                              "recorded_extraction": []})

    def test_latest_plan_per_member(self):
        ep = replayed(4)   # David booked his flight (a plan)
        self.assertEqual([(p["name"], p["check"]) for p in ep.plans()], [("David", None)])
        ep.add_update({"update_id": "p2", "at": "2026-10-19T21:00:00+01:00", "kind": "note", "topic": "plan", "author": "david",
                       "text": "Flight moved: landing Wednesday at noon.", "recorded_extraction": []})
        self.assertEqual([p["text"] for p in ep.plans()], ["Flight moved: landing Wednesday at noon."])

    def test_a_plan_made_before_going_home_changed_is_flagged(self):
        ep = Episode(FULL)
        for u in FULL["updates"]:
            ep.add_update(u)
            if u["update_id"] == "u05":   # going home on Friday, if she walks safely
                break
        self.plan(ep, "p1", "2026-10-21T10:00:00+01:00")
        self.assertIsNone(ep.plans()[0]["check"])
        ep.add_update(FULL["updates"][[u["update_id"] for u in FULL["updates"]].index("u07")])   # now Saturday
        check = ep.plans()[0]["check"]
        self.assertIn("Going home changed after this to Sat 24 Oct", check)
        self.assertIn("is your plan still right?", check)

    def test_two_answers_and_going_home_end_the_check(self):
        ep = Episode(FULL)
        for u in FULL["updates"]:
            ep.add_update(u)
            if u["update_id"] == "u07b":
                break
        self.plan(ep, "p1", "2026-10-23T09:00:00+01:00")
        self.assertIn("Going home is not settled yet", ep.plans()[0]["check"])
        self.assertIsNone(next(p for p in ep.plans() if p["name"] == "David")["check"])   # his flight is not about going home
        for u in FULL["updates"][[u["update_id"] for u in FULL["updates"]].index("u07c"):]:
            if u["update_id"] == "u09":
                break
            ep.add_update(u)
        self.assertEqual(ep.plans()[0]["check"], "Going home was settled after this: Sat 24 Oct morning. Is your plan still right?")
        ep.add_update(FULL["updates"][[u["update_id"] for u in FULL["updates"]].index("u09")])
        self.assertIsNone(ep.plans()[0]["check"])   # she has gone home


class TestGrounding(unittest.TestCase):
    TEXT = "Enoxaparin 40 mg injection once a day for 28 days. The plan is surgery tomorrow at about 9 a.m."

    def test_rules(self):
        ok = {"type": "medication", "name": "Enoxaparin", "dose": "40 mg injection", "frequency": "once a day for 28 days",
              "status": "new", "quote": "Enoxaparin 40 mg injection once a day for 28 days"}
        self.assertIsNone(grounding_problem(ok, self.TEXT))
        cases = [({**ok, "quote": "Enoxaparin 80 mg injection"}, "quote not found"),
                 ({**ok, "quote": "Enoxaparin 40"}, "shorter than 3 words"),
                 ({**ok, "dose": "60 mg injection"}, "dose states 60"),
                 ({**ok, "status": "maybe"}, "medication status"),
                 ({**ok, "name": ""}, "missing name"),
                 ({**ok, "type": "prognosis"}, "unknown fact type"),
                 ({**ok, "dose": 40}, "not text"),
                 ({"type": "procedure_planned", "what": "Surgery", "when": "tomorrow", "quote": "The plan is surgery tomorrow"}, "ISO"),
                 ({"type": "procedure_planned", "what": "Surgery", "when_text": "at about 10 a.m.", "quote": "The plan is surgery tomorrow"},
                  "when_text states 10")]
        for fact, why in cases:
            self.assertIn(why, grounding_problem(fact, self.TEXT) or "", fact)

    def test_rejected_facts_are_kept_out(self):
        ep = Episode(SCENARIO)
        u = copy.deepcopy(SCENARIO["updates"][1])
        u["recorded_extraction"].append({"type": "diagnosis_stated", "what": "Hip fracture and a heart attack",
                                         "quote": "she also had a heart attack"})
        e = ep.add_update(u)
        self.assertEqual(len(e["rejected"]), 1)
        self.assertNotIn("heart", ep.status()["said_by_doctor"]["text"])


class TestViewers(unittest.TestCase):
    def test_time_zones(self):
        ep = replayed(2)
        surgery = lambda m: next(ln["text"] for e in ep.timeline(m) for ln in e["lines"] if ln["type"] == "procedure_planned")  # noqa: E731
        self.assertEqual(surgery("anna"), "Hip surgery planned: Tue 20 Oct 09:00")
        self.assertEqual(surgery("mia"), "Hip surgery planned: Tue 20 Oct 19:00")
        self.assertEqual(surgery("david"), "Hip surgery planned: Tue 20 Oct 04:00")
        self.assertEqual(ep.status(tz="Australia/Melbourne")["next"], ["Hip surgery planned: Tue 20 Oct 19:00"])

    def test_read_state(self):
        ep = replayed(3)
        self.assertEqual(ep.unread("mia"), 3)
        self.assertIsNone(ep.seen_at["mia"])
        ep.mark_read("mia")
        self.assertEqual(ep.seen_at["mia"], SCENARIO["updates"][2]["at"])
        ep.add_update(SCENARIO["updates"][3])
        self.assertEqual(ep.unread("mia"), 1)
        self.assertEqual([e["new"] for e in ep.timeline("mia")], [True, False, False, False])
        self.assertEqual(ep.unread("anna"), 4)
        with self.assertRaises(ValueError):
            ep.mark_read("stranger")

    def test_bad_updates(self):
        ep = replayed(1)
        with self.assertRaises(ValueError):
            ep.add_update(SCENARIO["updates"][0])            # twice
        with self.assertRaises(ValueError):
            ep.add_update({"update_id": "x", "at": "2026-10-19T09:00:00+01:00", "kind": "video", "text": "x"})
        with self.assertRaises(ValueError):
            ep.add_update({"update_id": "y", "at": "2026-10-19", "kind": "note", "text": "x"})


def upd(uid, at, kind, text, facts, **extra) -> dict:
    return {"update_id": uid, "at": at, "kind": kind, "author": "anna", "text": text, "recorded_extraction": facts, **extra}


class TestReviewRegressions(unittest.TestCase):
    """Cases from the review of the first version; each one used to give the family a wrong picture."""

    def test_other_procedure_done_does_not_complete_the_planned_surgery(self):
        ep = replayed(3)
        e = ep.add_update(upd("x1", "2026-10-19T16:00:00+01:00", "recording", "We gave her a blood transfusion this afternoon.",
                              [{"type": "procedure_done", "what": "Blood transfusion", "quote": "We gave her a blood transfusion"}]))
        self.assertEqual(e["rejected"], [])
        self.assertEqual(ep.phase(), "Waiting for hip surgery")
        self.assertEqual(ep.status(now="2026-10-19T16:00:00+01:00")["next"], ["Hip surgery planned: Tue 20 Oct 09:00"])

    def test_family_never_overrides_follow_ups_medicines_or_procedures(self):
        ep = replayed(3)
        e = ep.add_update(upd("x2", "2026-10-19T18:00:00+01:00", "note", "A friend said the hip surgery was done this evening.",
                              [{"type": "procedure_done", "what": "Hip surgery", "quote": "the hip surgery was done this evening"}]))
        self.assertEqual(ep.phase(), "Waiting for hip surgery")
        self.assertTrue(e["headline"].startswith("Family reports: "))
        ep = replayed()
        ep.add_update(upd("x3", "2026-10-25T09:00:00+00:00", "note",
                          "The fracture clinic appointment is on Thursday 3 December at 2 p.m. She will stop the Enoxaparin injections.",
                          [{"type": "follow_up", "what": "Fracture clinic appointment", "when_text": "Thursday 3 December at 2 p.m.",
                            "when": "2026-12-03T14:00", "quote": "The fracture clinic appointment is on Thursday 3 December at 2 p.m."},
                           {"type": "medication", "name": "Enoxaparin", "status": "stop", "quote": "She will stop the Enoxaparin injections"}]))
        s = ep.status(now="2026-10-25T09:00:00+00:00")
        self.assertIn("Fracture clinic appointment: Mon 30 Nov 10:30", s["next"])
        self.assertIn("New: Enoxaparin 40 mg injection once a day for 28 days", [m["text"] for m in s["medicines"] if m["active"]])

    def test_family_report_that_agrees_is_not_flagged(self):
        ep = replayed(3)
        e = ep.add_update(upd("x4", "2026-10-19T19:00:00+01:00", "note", "She is in Ward 5B, bed 12 now.",
                              [{"type": "location", "unit": "Ward 5B", "bed": "12", "quote": "She is in Ward 5B, bed 12"}]))
        self.assertIn("the care team said", e["lines"][0]["text"])
        ep2 = replayed(2)
        e2 = ep2.add_update(upd("x5", "2026-10-19T19:00:00+01:00", "note", "Physio says she can stand. Ward 5B, bed 12 is near the window.",
                                [{"type": "location", "hospital": "", "unit": "Orthopaedic ward 5B", "bed": "12",
                                  "quote": "Ward 5B, bed 12 is near the window"}]))
        self.assertEqual(e2["rejected"][0]["reason"], "unit says 'orthopaedic', which the quote does not")

    def test_family_home_note_while_in_hospital_and_readmission(self):
        ep = replayed(7)
        e = ep.add_update(upd("x6", "2026-10-22T18:00:00+01:00", "note", "Mum went home today, I think.",
                              [{"type": "discharged", "quote": "Mum went home today"}]))
        self.assertFalse(e["lines"][0]["applied"])
        self.assertEqual(ep.phase(), "Current patient status needs confirmation")
        self.assertEqual(ep.status()["location"]["text"], "St Mary's Hospital, Orthopaedic ward 5B, bed 12")
        ep = replayed()
        self.assertEqual([h["fact"]["unit"] for h in ep.slots["location"]["history"]], ["A&E", "Orthopaedic ward 5B"])
        ep.add_update(upd("x7", "2026-10-28T22:00:00+00:00", "recording", "We are admitting her to Ward 6, bed 3. She could go home on Monday.",
                          [{"type": "admitted", "quote": "We are admitting her to Ward 6"},
                           {"type": "location", "unit": "Ward 6", "bed": "3", "quote": "admitting her to Ward 6, bed 3"},
                           {"type": "expected_discharge", "when_text": "Monday", "when": "2026-11-02", "quote": "She could go home on Monday"}],
                          speaker="Emergency doctor"))
        s = ep.status(now="2026-10-28T22:00:00+00:00")
        self.assertEqual(ep.phase(), "Current patient status needs confirmation")
        self.assertTrue(s["discharged"]["time_uncertain"])
        self.assertIn("Ward 6", s["discharged"]["uncertain_alternatives"][0]["fact"]["quote"])

    def test_reschedules_say_what_changed(self):
        ep = replayed(3)
        e = ep.add_update(upd("x8", "2026-10-19T17:00:00+01:00", "recording", "Sorry, the operation has been moved to Wednesday at 2 p.m.",
                              [{"type": "procedure_planned", "what": "Operation", "when_text": "Wednesday at 2 p.m.",
                                "when": "2026-10-21T14:00", "quote": "the operation has been moved to Wednesday at 2 p.m."}]))
        self.assertEqual(e["headline"], "Operation moved: Tue 20 Oct 09:00 -> Wed 21 Oct 14:00")
        self.assertEqual(ep.status(now="2026-10-19T17:00:00+01:00")["next"], ["Operation planned: Wed 21 Oct 14:00"])
        ep = replayed(5)
        e = ep.add_update(upd("x9", "2026-10-22T10:00:00+01:00", "recording", "Going home on Friday is confirmed.",
                              [{"type": "expected_discharge", "when_text": "Friday", "when": "2026-10-23",
                                "quote": "Going home on Friday is confirmed"}]))
        self.assertEqual(e["headline"], "Expected to go home: Fri 23 Oct (no longer conditional)")
        ep = replayed()
        e = ep.add_update(upd("x10", "2026-10-26T09:00:00+00:00", "recording", "The fracture clinic appointment is moved to Tuesday 1 December at 9:15.",
                              [{"type": "follow_up", "what": "Fracture clinic appointment", "when_text": "Tuesday 1 December at 9:15",
                                "when": "2026-12-01T09:15", "quote": "The fracture clinic appointment is moved to Tuesday 1 December at 9:15"}]))
        self.assertEqual(e["headline"], "Fracture clinic appointment moved: Mon 30 Nov 10:30 -> Tue 01 Dec 09:15")

    def test_late_upload_does_not_undo_a_newer_statement(self):
        ep = replayed(4)
        ep.add_update(SCENARIO["updates"][6])   # Thu: Saturday morning
        e = ep.add_update(SCENARIO["updates"][4])   # Tue surgeon recording, uploaded after
        self.assertEqual(ep.slots["expected_discharge"]["fact"]["when"], "2026-10-24")
        self.assertIn("added late", next(ln["text"] for ln in e["lines"] if ln["type"] == "expected_discharge"))
        self.assertEqual(ep.timeline()[0]["update_id"], "u07")
        self.assertEqual(ep.latest_at(), "2026-10-22T16:20:00+01:00")

    def test_times_are_the_hospital_wall_clock(self):
        ep = replayed(8)
        u = copy.deepcopy(SCENARIO["updates"][8])
        u["recorded_extraction"][3]["when"] = "2026-11-30T10:30:00+01:00"   # the update's offset, wrong after the clock change
        ep.add_update(u)
        self.assertIn("Fracture clinic appointment: Mon 30 Nov 10:30", ep.status(tz="Europe/London")["next"])
        self.assertIn("Fracture clinic appointment: Mon 30 Nov 21:30", ep.status(tz="Australia/Melbourne")["next"])
        ep = replayed(1)
        u = copy.deepcopy(SCENARIO["updates"][1])
        u["recorded_extraction"][3]["when"] = "2026-10-20T09:00:00"   # no offset
        ep.add_update(u)
        self.assertEqual(ep.status(tz="America/Toronto")["next"], ["Hip surgery planned: Tue 20 Oct 04:00"])
        with self.assertRaises(ValueError):
            ep.add_update(upd("x11", "2026-10-19T09:00:00", "note", "x", []))

    def test_dates_must_agree_with_the_words(self):
        text = "The plan is surgery tomorrow morning. The follow-up is on Monday 30 November."
        at = "2026-10-19T11:15:00+01:00"
        base = {"type": "follow_up", "what": "Follow-up", "when_text": "Monday 30 November", "quote": "The follow-up is on Monday 30 November"}
        self.assertIsNone(grounding_problem({**base, "when": "2026-11-30"}, text, at))
        self.assertIn("too far", grounding_problem({**base, "when_text": "30 November", "when": "2025-11-30"}, text, at))
        self.assertIn("but the words say Monday", grounding_problem({**base, "when": "2026-12-01"}, text, at))
        ep = replayed(1)
        e = ep.add_update(upd("x12", at, "recording", text,
                              [{"type": "procedure_planned", "what": "Hip surgery", "when_text": "tomorrow morning",
                                "when": "2026-10-20T08:00:00+01:00", "quote": "The plan is surgery tomorrow morning"}]))
        self.assertEqual(e["lines"][0]["text"], "Hip surgery planned: Tue 20 Oct morning")   # no invented 08:00

    def test_quote_must_support_the_values(self):
        med = SCENARIO["updates"][7]["text"]
        bad = [({"type": "medication", "name": "Ibuprofen", "status": "new", "quote": "STOP taking Ibuprofen"}, "quote says stop"),
               ({"type": "medication", "name": "Warfarin", "dose": "15 mg", "frequency": "once a day", "status": "new",
                 "quote": "Lansoprazole 15 mg once a day"}, "name says 'warfarin'"),
               ({"type": "medication", "name": "Lansoprazole", "dose": "1.5 mg", "status": "new",
                 "quote": "Lansoprazole 15 mg once a day"}, "dose states 1.5"),
               ({"type": "medication", "name": "Enoxaparin", "dose": "40 mg injection", "frequency": "twice a day for 28 days",
                 "status": "new", "quote": "Enoxaparin 40 mg injection once a day for 28 days"}, "frequency says 'twice'")]
        for fact, why in bad:
            self.assertIn(why, grounding_problem(fact, med) or "", fact)
        ward = SCENARIO["updates"][2]["text"]
        self.assertIn("value states 946", grounding_problem({"type": "contact", "what": "Ward phone", "value": "020 946 0123",
                                                              "quote": "Ward phone: 020 7946 0123"}, ward))
        self.assertIn("says 'cancelled'", grounding_problem({"type": "procedure_planned", "what": "Hip surgery cancelled",
                                                             "quote": "The plan is surgery tomorrow morning"},
                                                            SCENARIO["updates"][1]["text"]))

    def test_discharge_needs_a_completed_event(self):
        text = "She can go home today. She can't go home today, the pharmacy is late."
        self.assertIn("discharged needs", grounding_problem({"type": "discharged", "quote": "She can go home today"}, text))
        self.assertIn("negation", grounding_problem({"type": "expected_discharge", "when_text": "today",
                                                     "quote": "go home today, the pharmacy"}, text))

    def test_diagnosis_is_attributed_to_its_source(self):
        ep = replayed(1)
        e = ep.add_update(upd("x13", "2026-10-19T09:30:00+01:00", "note", "I think she has broken her hip.",
                              [{"type": "diagnosis_stated", "what": "Broken hip", "quote": "she has broken her hip"}]))
        self.assertEqual(e["headline"], "The family says: broken hip")
        self.assertEqual(e["headline_flag"], "unconfirmed")

    def test_malformed_model_facts_are_rejected_not_raised(self):
        ep = replayed(1)
        u = copy.deepcopy(SCENARIO["updates"][1])
        u["recorded_extraction"][2]["bed"] = 12
        u["recorded_extraction"] += [{"type": "procedure_planned", "what": "Surgery", "when": 1760868900, "quote": "The plan is surgery tomorrow morning"},
                                     {"type": ["event"], "what": "x", "quote": "The X-ray shows a fracture"}, "garbage"]
        e = ep.add_update(u)
        self.assertEqual(len(e["facts"]), 6)
        self.assertEqual(len(e["rejected"]), 3)
        self.assertEqual(ep.status()["location"]["text"], "St Mary's Hospital, Orthopaedic ward 5B, bed 12")


class StubLLM:
    def __init__(self, facts):
        self.facts, self.calls = facts, []

    def chat(self, messages, json_schema=None, schema_name="reply"):
        self.calls.append(messages[-1]["content"])
        return {"text": "{...}", "json": {"facts": self.facts}, "latency_s": 0.1, "json_mode": "prompted_json"}


class TestLiveExtractor(unittest.TestCase):
    def test_model_facts_are_grounded(self):
        u = {k: v for k, v in SCENARIO["updates"][1].items() if k != "recorded_extraction"}
        good = SCENARIO["updates"][1]["recorded_extraction"][:2]
        made_up = {"type": "procedure_planned", "what": "Hip surgery", "when": "2026-10-20T08:00:00+01:00",
                   "when_text": "at 8 a.m.", "quote": "surgery tomorrow morning at 8 a.m."}
        llm = StubLLM(good + [made_up])
        ex = llm_extractor(llm)
        ep = Episode(SCENARIO)
        e = ep.add_update(u, extractor=ex)
        self.assertEqual(e["method"], "llm")
        self.assertEqual(len(e["facts"]), 2)
        self.assertEqual(len(e["rejected"]), 1)
        self.assertIn("Monday 19 October 2026, 11:15", llm.calls[0])   # relative dates are resolved from this
        self.assertEqual(len(ex.log), 1)
        self.assertTrue(ex.log[0]["parsed"])

    def test_garbage_reply_adds_an_empty_entry(self):
        ep = Episode(SCENARIO)
        u = {k: v for k, v in SCENARIO["updates"][0].items() if k != "recorded_extraction"}

        class Garbage(StubLLM):
            def chat(self, *a, **k):
                return {"text": "no", "json": None, "latency_s": 0.1, "json_mode": "prompted_json"}
        e = ep.add_update(u, extractor=llm_extractor(Garbage([])))
        self.assertEqual((e["facts"], e["headline"]), ([], "Note from the family"))
        ex = llm_extractor(Garbage([]))
        ep.add_update({**u, "update_id": "u01b"}, extractor=ex)
        self.assertFalse(ex.log[-1]["parsed"])


class VisionStub:
    model = "vision-stub"

    def __init__(self, text, finish_reason="stop"):
        self.text, self.finish_reason, self.messages = text, finish_reason, []

    def chat(self, messages, json_schema=None, schema_name="reply"):
        self.messages.append(messages)
        return {"text": self.text, "json": None, "latency_s": 2.5, "json_mode": "text", "finish_reason": self.finish_reason}


class TestPhotos(unittest.TestCase):
    PHOTO = HERE.parent / "care_cases" / "photos" / "discharge_medication_list.jpg"

    def test_reader_sends_the_image_and_returns_the_text(self):
        image = self.PHOTO.read_bytes()
        self.assertEqual(photo_reader(VisionStub("```paracetamol 1 g four times a day\nSTOP taking Ibuprofen```"))(image)["text"],
                         "paracetamol 1 g four times a day\nSTOP taking Ibuprofen")   # a word right after the fence is kept
        self.assertEqual(photo_reader(VisionStub("```Text\nLansoprazole 15 mg once a day.\n```"))(image)["text"],
                         "Lansoprazole 15 mg once a day.")
        llm = VisionStub("```\nDISCHARGE MEDICATIONS\nLansoprazole 15 mg once a day.\n```")
        read = photo_reader(llm)
        r = read(image, "image/jpeg")
        parts = llm.messages[0][0]["content"]
        self.assertEqual([p["type"] for p in parts], ["text", "image_url"])
        url = parts[1]["image_url"]["url"]
        self.assertTrue(url.startswith("data:image/jpeg;base64,"))
        self.assertEqual(base64.b64decode(url.split(",", 1)[1]), image)
        self.assertEqual(r["text"], "DISCHARGE MEDICATIONS\nLansoprazole 15 mg once a day.")   # code block removed
        self.assertTrue(r["parsed"])
        self.assertEqual((r["model"], r["image_bytes"], len(read.log)), ("vision-stub", len(image), 1))
        self.assertNotIn("base64", str(read.log))   # the log never keeps the image
        self.assertFalse(photo_reader(VisionStub("", "stop"))(image)["parsed"])
        self.assertFalse(photo_reader(VisionStub("DISCHARGE MED", "length"))(image)["parsed"])
        with self.assertRaises(ValueError):
            read(image, "application/pdf")
        with self.assertRaises(ValueError):
            read(b"", "image/png")

    def test_photo_model_can_differ_from_the_main_model(self):
        """CARERELAY_PHOTO_MODEL: a vision model for photos when the model for facts and questions takes no images
        (Token Factory on 2026-10-16 listed no Gemma); unset, photos use CARERELAY_LLM_MODEL."""
        import os
        from llm_client import make_client, make_photo_client
        saved = {k: os.environ.get(k) for k in ("CARERELAY_LLM_MODEL", "CARERELAY_PHOTO_MODEL", "CARERELAY_LLM_BACKEND")}
        try:
            os.environ.pop("CARERELAY_LLM_BACKEND", None)
            os.environ["CARERELAY_LLM_MODEL"] = "text-model"
            os.environ.pop("CARERELAY_PHOTO_MODEL", None)
            self.assertEqual(make_photo_client(max_tokens=10).model, "text-model")
            self.assertEqual(make_photo_client(model="given").model, "given")
            os.environ["CARERELAY_PHOTO_MODEL"] = "vision-model"
            self.assertEqual(make_photo_client(max_tokens=10).model, "vision-model")
            self.assertEqual(make_photo_client(model="given").model, "vision-model")
            self.assertEqual(make_client(max_tokens=10).model, "text-model")   # facts and questions keep the main model
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    def test_demo_photo_text_is_what_is_printed(self):
        src = (self.PHOTO.parent / "make_sample_photos.py").read_text()
        printed = ast.literal_eval(src.split("TEXT = ", 1)[1].split("\n]", 1)[0] + "\n]")
        u08 = next(u for u in SCENARIO["updates"] if u["update_id"] == "u08")
        self.assertEqual(u08["text"], "\n".join(printed))
        self.assertTrue((HERE.parent / "care_cases" / u08["image"]).is_file())
        e = replayed(7).add_update(u08)
        self.assertEqual((e["image"], e["reading"]["method"], e["rejected"]), (u08["image"], "recorded", []))

    def test_prompted_json_keeps_image_parts(self):
        from llm_client import OpenAIChat
        client = OpenAIChat(base_url="http://127.0.0.1:9/v1", model="m")
        client.guided_json_supported = False
        sent = []
        client._request = lambda path, payload=None: sent.append(payload) or {"choices": [{"message": {"content": "{}"}}]}
        parts = [{"type": "text", "text": "read this"}, {"type": "image_url", "image_url": {"url": "data:image/png;base64,AA=="}}]
        client.chat([{"role": "user", "content": parts}], json_schema={"type": "object"})
        out = sent[0]["messages"][-1]["content"]
        self.assertEqual(out[:2], parts)
        self.assertEqual(out[2]["type"], "text")
        self.assertIn("JSON", out[2]["text"])

    def test_checked_reading_becomes_a_care_team_photo_update(self):
        ep = replayed(7)
        text = "Paracetamol 1 g four times a day as needed for pain.\nSTOP taking Ibuprofen."
        e = ep.add_update({"update_id": "c01", "at": "2026-10-24T10:30:00+01:00", "kind": "photo", "author": "anna",
                           "photo_of": "Medication list", "text": text, "image": None,
                           "reading": {"method": "model", "model": "vision-stub", "checked_by": "Anna", "edited": True}},
                          extractor=llm_extractor(StubLLM([
                              {"type": "medication", "name": "Paracetamol", "dose": "1 g", "frequency": "four times a day as needed for pain",
                               "status": "new", "quote": "Paracetamol 1 g four times a day as needed for pain"},
                              {"type": "medication", "name": "Ibuprofen", "status": "stop", "quote": "STOP taking Ibuprofen"}])))
        self.assertEqual(e["headline"], "Medication list updated: 1 new, 1 stopped, 0 continued or changed")
        self.assertEqual(e["authority"], "care_team")
        self.assertTrue(e["reading"]["edited"])

    def test_lines_the_caregiver_changed_are_family_reports(self):
        ep = replayed(7)
        text = "Lansoprazole 15 mg once a day.\nSTOP taking Ibuprofen."
        e = ep.add_update({"update_id": "c01", "at": "2026-10-24T10:30:00+01:00", "kind": "photo", "author": "anna",
                           "photo_of": "Medication list", "text": text, "image": None,
                           "reading": {"method": "model", "model_text": "Lansoprazole 1.5 mg once a day.\nSTOP taking Ibuprofen.",
                                       "changed_lines": ["Lansoprazole 15 mg once a day."]}},
                          facts=[{"type": "medication", "name": "Lansoprazole", "dose": "15 mg", "frequency": "once a day",
                                  "status": "new", "quote": "Lansoprazole 15 mg once a day"},
                                 {"type": "medication", "name": "Ibuprofen", "status": "stop", "quote": "STOP taking Ibuprofen"}])
        flags = {ln["fact"]["name"]: ln["unconfirmed"] for ln in e["lines"]}
        self.assertEqual(flags, {"Lansoprazole": True, "Ibuprofen": False})
        meds = {m["text"]: m["unconfirmed"] for m in ep.status()["medicines"]}
        self.assertTrue(meds["New: Lansoprazole 15 mg once a day"])
        self.assertFalse(meds["Stopped: Ibuprofen"])



class TestChangedLines(unittest.TestCase):
    def test_a_changed_line_inside_another_line_marks_only_its_own(self):
        ep = Episode(copy.deepcopy(SCENARIO))
        ep.add_update(ep.next_scripted())
        text = "Take Amlodipine 5 mg once a day with Ramipril.\nAmlodipine 5 mg once a day"
        e = ep.add_update({"update_id": "c01", "at": ep.latest_at(), "kind": "photo", "author": "anna", "photo_of": "List",
                           "text": text, "reading": {"method": "model", "changed_lines": ["Amlodipine 5 mg once a day"]}},
                          facts=[{"type": "medication", "name": "Ramipril", "status": "new",
                                  "quote": "Take Amlodipine 5 mg once a day with Ramipril"},
                                 {"type": "medication", "name": "Amlodipine", "dose": "5 mg", "frequency": "once a day",
                                  "status": "continue", "quote": "Amlodipine 5 mg once a day"}])
        by_name = {ln["fact"]["name"]: ln for ln in e["lines"]}
        self.assertFalse(by_name["Ramipril"]["unconfirmed"])   # the care team's line, not changed
        self.assertTrue(by_name["Amlodipine"]["unconfirmed"])   # the changed line: the family's words


class TestFamilyGuessIsNotThePlan(unittest.TestCase):
    def test_the_care_teams_plan_does_not_move_from_a_family_guess(self):
        ep = Episode(copy.deepcopy(SCENARIO))
        ep.add_update(ep.next_scripted())
        at = ep.latest_at()
        ep.add_update({"update_id": "c01", "at": at, "kind": "note", "author": "david", "text": "She'll be home Thursday."},
                      facts=[{"type": "expected_discharge", "when_text": "Thursday", "when": "2026-10-22", "quote": "She'll be home Thursday"}])
        e = ep.add_update({"update_id": "c02", "at": at, "kind": "recording", "author": "anna", "speaker": "Surgeon",
                           "text": "She can go home on Saturday."},
                          facts=[{"type": "expected_discharge", "when_text": "Saturday", "when": "2026-10-24",
                                  "quote": "She can go home on Saturday"}])
        self.assertEqual(e["headline"], "Expected to go home: Sat 24 Oct")   # not "Going home moved: Thu 22 Oct -> ..."
        self.assertIsNone(e["lines"][0]["changed_from"])
        self.assertIsNone(ep.status()["expected_discharge"]["was"])


class TestQuestionsForTheDoctor(unittest.TestCase):
    def test_the_same_question_joins_and_answered_ones_close(self):
        ep = Episode(copy.deepcopy(SCENARIO))
        ep.add_update(ep.next_scripted())
        q1, joined = ep.add_question("Will she need a wheelchair at home?", "mia")
        self.assertFalse(joined)
        q2, joined = ep.add_question("will she need a  wheelchair at home", "david")
        self.assertTrue(joined)
        self.assertIs(q1, q2)
        self.assertEqual(q1["askers"], ["mia", "david"])
        q3, joined = ep.add_question("How long will the physio last?", "mia")
        self.assertFalse(joined)
        self.assertEqual([q["qid"] for q in ep.questions], ["q1", "q2"])
        ep.set_answered("q1", update_id="u05")
        self.assertEqual((q1["status"], q1["answered_by"]), ("answered", "u05"))
        q4, joined = ep.add_question("Will she need a wheelchair at home?", "joy")   # answered: a new one
        self.assertFalse(joined)
        with self.assertRaises(ValueError):
            ep.add_question("   ", "mia")
        with self.assertRaises(ValueError):
            ep.add_question("Who?", "stranger")
        self.assertEqual(ep.add_question("Does she need a wheelchair at home?", "joy")[1], "already")   # asked it already

    def test_different_questions_stay_apart(self):
        for a, b in (("Does she need the injections every day?", "Does she need the injections twice a day?"),
                     ("Is the swelling in her left leg normal?", "Is the swelling in her right leg normal?"),
                     ("Can she shower before physio?", "Can she shower after physio?"),
                     ("Is it safe for her to sleep on her side?", "Is it not safe for her to sleep on her side?"),
                     ("Will the staples come out in 10 days?", "Will the staples come out in 12 days?"),
                     ("Where is the fracture clinic?", "When is the fracture clinic?"),
                     ("How long will she need the injections?", "Why does she need the injections?"),
                     ("Will the stitches come out?", "When will the stitches come out?"),
                     ("Should mum stop the enoxaparin injections?", "Should mum continue the enoxaparin injections?")):
            ep = Episode(copy.deepcopy(SCENARIO))
            ep.add_question(a, "anna")
            q, joined = ep.add_question(b, "mia")
            self.assertFalse(joined, (a, b))
            self.assertEqual([x["text"] for x in ep.questions], [a, b])
        ep = Episode(copy.deepcopy(SCENARIO))
        ep.add_question("Will she need a wheelchair at home?", "anna")
        self.assertEqual(ep.add_question("Does she need a wheelchair at home?", "mia")[1], "joined")   # the same question

    def test_a_question_keeps_when_it_was_asked(self):
        ep = Episode(copy.deepcopy(SCENARIO))
        for _ in range(3):
            ep.add_update(ep.next_scripted())
        self.assertEqual(ep.add_question("Will she get injections at home?", "anna", asked_seq=1)[0]["asked_seq"], 1)
        self.assertEqual(ep.add_question("Will she need a frame?", "anna", asked_seq=99)[0]["asked_seq"], 3)   # never later than now
        q = ep.set_answered("q1", by="mia")
        self.assertEqual((q["status"], q["answered_by"], q["marked_by"]), ("answered", None, "mia"))
        q = ep.set_answered("q1", answered=False)
        self.assertEqual((q["status"], q["marked_by"]), ("open", None))

class TestCompletedDischargeNotices(unittest.TestCase):
    PAPER = ("Hospital discharge summary.\nPatient: Elena Novak.\nDate of discharge: 24 October 2026.\n"
             "Discharge destination: Home.")
    RECEIVED = "2026-10-25T15:00:00+00:00"

    def fact(self, text=None, when="2026-10-24"):
        return {"type": "discharged", "when": when, "quote": text or self.PAPER}

    def test_completed_discharge_fields_are_grounded(self):
        for paper in (self.PAPER, self.PAPER.replace("24 October 2026", "2026-10-24")):
            with self.subTest(paper=paper):
                self.assertIsNone(grounding_problem(self.fact(paper), paper, self.RECEIVED))
                ep = Episode(SCENARIO)
                ep.add_update({"update_id": "notice", "at": self.RECEIVED, "kind": "photo", "author": "anna",
                               "photo_of": "Hospital discharge summary", "text": paper}, facts=[self.fact(paper)])
                self.assertEqual(ep.phase(), "Home after hospital")
                self.assertFalse(ep.status()["discharged"]["unconfirmed"])

    def test_planned_draft_future_or_title_only_is_not_completed_discharge(self):
        field_quote = self.PAPER.split("Date of discharge:", 1)[1]
        field_quote = "Date of discharge:" + field_quote
        cases = [("Draft discharge instructions.\n" + field_quote, field_quote, self.RECEIVED),
                 ("Planned discharge notice.\n" + field_quote, field_quote, self.RECEIVED),
                 ("She has not been discharged.\n" + field_quote, field_quote, self.RECEIVED),
                 (self.PAPER, self.PAPER, "2026-10-23T15:00:00+01:00"),
                 ("Hospital discharge summary. Stand up slowly.", "Hospital discharge summary", self.RECEIVED)]
        for text, quote, at in cases:
            with self.subTest(text=text, at=at):
                self.assertIsNotNone(grounding_problem(self.fact(quote), text, at))

    def test_conflicting_date_destination_or_resolved_date_requires_review(self):
        for text, when in ((self.PAPER, "2026-10-23"),
                           ("She has been discharged.\n" + self.PAPER, "2026-10-23"),
                           (self.PAPER + "\nDate of discharge: 23 October 2026.", "2026-10-24"),
                           (self.PAPER + "\nDate of discharge: Not supplied.", "2026-10-24"),
                           (self.PAPER + "\nDischarge destination: Rehabilitation unit.", "2026-10-24"),
                           (self.PAPER + "\nCurrent location: Orthopaedic ward.", "2026-10-24")):
            with self.subTest(text=text, when=when):
                self.assertIsNotNone(grounding_problem(self.fact(text, when), text, self.RECEIVED))

    def test_a_negated_or_future_resolved_discharge_is_not_completed(self):
        for text, when in (("She has not been discharged.", "2026-10-24"),
                           ("She has been discharged.", "2026-10-26")):
            with self.subTest(text=text, when=when):
                self.assertIsNotNone(grounding_problem(self.fact(text, when), text, self.RECEIVED))

    def test_old_notice_does_not_undo_a_more_recent_readmission(self):
        ep = Episode(SCENARIO)
        text = "We are admitting her again to Ward 7."
        ep.add_update({"update_id": "readmission", "at": "2026-10-25T09:00:00+00:00", "kind": "recording",
                       "author": "anna", "speaker": "Emergency doctor", "text": text},
                      facts=[{"type": "admitted", "quote": text}])
        entry = ep.add_update({"update_id": "notice", "at": self.RECEIVED, "kind": "photo", "author": "anna",
                               "photo_of": "Old discharge summary", "text": self.PAPER}, facts=[self.fact()])
        self.assertEqual(entry["rejected"], [])
        self.assertFalse(entry["lines"][0]["applied"])
        self.assertTrue(entry["lines"][0]["late"])
        self.assertEqual(ep.phase(), "Admitted to hospital")
        self.assertIsNone(ep.status()["discharged"])

    def test_aftercare_does_not_negate_completed_discharge_fields(self):
        quote = "Date of discharge: 24 October 2026.\nDischarge destination: Home."
        for aftercare in ("After discharge, do not drive for six weeks.",
                          "After discharge, a planned review is in six weeks."):
            with self.subTest(aftercare=aftercare):
                text = self.PAPER + "\n" + aftercare
                ep = Episode(SCENARIO)
                entry = ep.add_update({"update_id": "notice", "at": self.RECEIVED, "kind": "photo",
                                       "author": "anna", "photo_of": "Hospital discharge summary", "text": text},
                                      facts=[self.fact(quote)])
                self.assertEqual(entry["rejected"], [])
                self.assertEqual(ep.phase(), "Home after hospital")
                self.assertEqual(entry["facts"][0]["quote"], quote)

    def test_aftercare_does_not_negate_a_completed_discharge_statement(self):
        for text in ("She has been discharged, but should not drive for six weeks.",
                     "She has been discharged and should not drive for six weeks.",
                     "She has been discharged. After discharge, do not drive for six weeks."):
            for quote in (text, "She has been discharged"):
                with self.subTest(text=text, quote=quote):
                    self.assertIsNone(grounding_problem(self.fact(quote), text, self.RECEIVED))

    def test_shared_modal_or_negation_is_not_lost_across_conjoined_verbs(self):
        for text in ("She can be reviewed and discharged today.",
                     "She could be reviewed and discharged today.",
                     "She will be reviewed and discharged today.",
                     "She has not been reviewed and discharged today."):
            with self.subTest(text=text):
                ep = Episode(SCENARIO)
                entry = ep.add_update({"update_id": "plan", "at": self.RECEIVED, "kind": "recording",
                                       "author": "anna", "speaker": "Ward doctor", "text": text},
                                      facts=[{"type": "discharged", "quote": text}])
                self.assertEqual(len(entry["rejected"]), 1)
                self.assertIsNone(ep.status()["discharged"])
        completed = "She has been reviewed and discharged today."
        self.assertIsNone(grounding_problem({"type": "discharged", "quote": completed}, completed, self.RECEIVED))

    def test_an_abbreviated_title_does_not_drop_the_governing_modal_or_negation(self):
        for text in ("She can be reviewed by Dr. Smith and discharged today.",
                     "She could be reviewed by Dr. Smith and discharged today.",
                     "She has not been reviewed by Dr. Smith and discharged today."):
            with self.subTest(text=text):
                ep = Episode(SCENARIO)
                entry = ep.add_update({"update_id": "plan", "at": self.RECEIVED, "kind": "recording",
                                       "author": "anna", "speaker": "Ward doctor", "text": text},
                                      facts=[{"type": "discharged", "quote": text}])
                self.assertEqual(len(entry["rejected"]), 1)
                self.assertIsNone(ep.status()["discharged"])
        text = "She has been reviewed by Dr. Smith and discharged today."
        self.assertIsNone(grounding_problem({"type": "discharged", "quote": text}, text, self.RECEIVED))

    def test_prospective_or_negated_event_still_blocks_a_completed_field_claim(self):
        quote = "Date of discharge: 24 October 2026.\nDischarge destination: Home."
        for event in ("Discharge is planned.", "Discharge is not confirmed.",
                      "She isn't ready for discharge.", "She will be discharged tomorrow."):
            with self.subTest(event=event):
                self.assertIsNotNone(grounding_problem(self.fact(quote), self.PAPER + "\n" + event, self.RECEIVED))

    def test_old_notice_does_not_undo_a_newer_hospital_location_without_admission(self):
        ep = Episode(SCENARIO)
        text = "She is back at St Mary's Hospital, Ward 7."
        ep.add_update({"update_id": "returned", "at": "2026-10-25T09:00:00+00:00", "kind": "recording",
                       "author": "anna", "speaker": "Ward doctor", "text": text},
                      facts=[{"type": "location", "hospital": "St Mary's Hospital", "unit": "Ward 7", "quote": text}])
        self.assertNotIn("admitted", ep.slots)
        entry = ep.add_update({"update_id": "notice", "at": self.RECEIVED, "kind": "photo", "author": "anna",
                               "photo_of": "Old discharge summary", "text": self.PAPER}, facts=[self.fact()])
        self.assertEqual(entry["rejected"], [])
        self.assertFalse(entry["lines"][0]["applied"])
        self.assertTrue(entry["lines"][0]["late"])
        self.assertIsNone(ep.status()["discharged"])
        self.assertEqual(ep.slots["location"]["fact"]["hospital"], "St Mary's Hospital")

    def test_extractor_requests_one_continuous_quote_and_keeps_split_facts_rejected(self):
        quote = "Date of discharge: 24 October 2026.\nDischarge destination: Home."
        update = {"update_id": "notice", "at": self.RECEIVED, "kind": "photo", "author": "anna",
                  "photo_of": "Hospital discharge summary", "text": self.PAPER}
        llm = StubLLM([self.fact(quote)])
        ep = Episode(SCENARIO)
        entry = ep.add_update(update, extractor=llm_extractor(llm))
        self.assertEqual((len(entry["facts"]), entry["rejected"]), (1, []))
        self.assertEqual(ep.phase(), "Home after hospital")
        self.assertIn("ONE discharged fact", llm.calls[0])
        self.assertIn("ONE continuous verbatim quote", llm.calls[0])
        self.assertIn('"quote": "Date of discharge: 24 October 2026. Discharge destination: Home."', llm.calls[0])
        split = StubLLM([self.fact("Date of discharge: 24 October 2026"),
                         {"type": "discharged", "quote": "Discharge destination: Home"}])
        rejected = Episode(SCENARIO).add_update(update, extractor=llm_extractor(split))
        self.assertEqual((len(rejected["facts"]), len(rejected["rejected"])), (0, 2))


class TestGroundedCareStatus(unittest.TestCase):
    def add_document(self, label, text, facts):
        ep = Episode(SCENARIO)
        ep.add_update({"update_id": "paper", "at": "2026-10-24T15:00:00+01:00", "kind": "photo",
                       "author": "anna", "photo_of": label, "text": text}, facts=facts)
        return ep

    def test_empty_profile_home_is_not_a_current_location(self):
        ep = Episode(SCENARIO)
        self.assertEqual(ep.patient["home"], "at home")
        self.assertEqual(ep.status()["phase"], "No updates yet")
        self.assertIsNone(ep.status()["location"])
        self.assertIsNone(ep.status()["discharged"])

    def test_safety_instructions_are_received_information_not_discharge(self):
        ep = self.add_document("Medicines and Safe Movement",
                               "Medicines and Safe Movement\nStand up slowly.\nMake the home safer today.",
                               [{"type": "instruction", "what": "Stand up slowly", "quote": "Stand up slowly"}])
        self.assertEqual(ep.status()["phase"], "Current patient status not confirmed")
        self.assertEqual(ep.status()["care_information"], "Care instructions received")
        self.assertIsNone(ep.status()["discharged"])
        self.assertIsNone(ep.status()["location"])

    def test_discharge_document_context_does_not_mean_discharge_occurred(self):
        for label, text in (("Discharge notice", "Stand up slowly."),
                            ("A document", "DISCHARGE INFORMATION\nStand up slowly.")):
            with self.subTest(label=label):
                ep = self.add_document(label, text,
                                       [{"type": "instruction", "what": "Stand up slowly", "quote": "Stand up slowly"}])
                self.assertEqual(ep.status()["phase"], "Current patient status not confirmed")
                self.assertEqual(ep.status()["care_information"], "Discharge information received")
                self.assertIsNone(ep.status()["discharged"])
                self.assertIsNone(ep.status()["location"])

    def test_medication_facts_identify_the_information_received(self):
        text = "Continue Paracetamol 500 mg twice daily."
        ep = self.add_document("Medication list", text,
                               [{"type": "medication", "name": "Paracetamol", "dose": "500 mg",
                                 "frequency": "twice daily", "status": "continue", "quote": text}])
        self.assertEqual(ep.status()["phase"], "Current patient status not confirmed")
        self.assertEqual(ep.status()["care_information"], "Medication information received")
        self.assertIsNone(ep.status()["discharged"])


class TestEventTimeContract(unittest.TestCase):
    """Source clocks resolve explicit relative words; they never invent event dates."""

    def entry(self, text, facts=None, kind="note", **extra):
        ep = Episode(SCENARIO)
        entry = ep.add_update(upd("time-1", "2026-10-17T09:20:00+01:00", kind, text,
                                  facts or [{"type": "family", "what": "Family will be there", "quote": text}],
                                  topic="plan" if kind == "note" else None, **extra))
        return ep, entry

    def test_exact_numeric_arrival_keeps_date_and_afternoon_without_a_clock(self):
        ep, entry = self.entry("I'll be there on 10/20 afternoon")
        temporal = entry["lines"][0]["event_time"]
        self.assertEqual(temporal["when"], "2026-10-20")
        self.assertEqual(temporal["precision"], "part_of_day")
        self.assertEqual(temporal["temporal_status"], "planned")
        self.assertEqual(temporal["source_quote"], "I'll be there on 10/20 afternoon")
        self.assertEqual(ep.plans()[0]["event_time"], temporal)

    def test_spoken_ordinal_and_relative_date_use_actual_reference_day(self):
        for text, expected in (("I'll arrive on October 20th in the afternoon", "2026-10-20"),
                               ("I will be there on October 20 in the afternoon.", "2026-10-20"),
                               ("I'll be there tomorrow afternoon", "2026-10-18"),
                               ("I'll be there next Tuesday afternoon", "2026-10-20")):
            with self.subTest(text=text):
                _, entry = self.entry(text)
                self.assertEqual(entry["event_time"]["when"], expected)
                self.assertEqual(entry["event_time"]["precision"], "part_of_day")

    def test_missing_ambiguous_and_multiple_dates_stay_pending(self):
        for text in ("I'll be there in the afternoon", "I'll be there on 10/11 afternoon",
                     "I'll be there on October 20 or October 21", "I'll arrive on October twentieth"):
            with self.subTest(text=text):
                _, entry = self.entry(text)
                self.assertIsNone(entry["event_time"]["when"])
                self.assertEqual(entry["event_time"]["status"], "pending_confirmation")

    def test_model_clock_and_unquoted_calendar_date_cannot_become_event_time(self):
        text = "The operation is planned for October 20 afternoon"
        ep, entry = self.entry(text, [{"type": "procedure_planned", "what": "Operation", "when_text": "October 20 afternoon",
                                      "when": "2026-10-20T08:00:00", "quote": text}], kind="recording")
        self.assertEqual(entry["event_time"]["when"], "2026-10-20")
        self.assertEqual(ep.status()["next"], ["Operation planned: Tue 20 Oct afternoon"])
        text = "She has been admitted to hospital"
        _, entry = self.entry(text, [{"type": "admitted", "when": "2026-10-17T08:00:00", "quote": text}], kind="recording")
        self.assertIsNone(entry["event_time"]["when"])

    def test_mixed_dates_have_individual_line_times(self):
        first, second = "She was admitted on October 16", "Surgery is planned for October 20 afternoon"
        _, entry = self.entry(first + ". " + second, [
            {"type": "admitted", "quote": first},
            {"type": "procedure_planned", "what": "Surgery", "quote": second}], kind="recording")
        self.assertEqual([line["event_time"]["when"] for line in entry["lines"]], ["2026-10-16", "2026-10-20"])
        self.assertIsNone(entry["event_time"]["when"])

    def test_late_old_location_uses_event_date_instead_of_received_date(self):
        ep = Episode(SCENARIO)
        for uid, source_at, text, unit in (
                ("new", "2026-10-17T09:00:00+01:00", "She moved to Ward 6 on October 17", "Ward 6"),
                ("old", "2026-10-17T10:00:00+01:00", "She moved to Ward 5 on October 16", "Ward 5")):
            entry = ep.add_update(upd(uid, source_at, "recording", text,
                                     [{"type": "location", "unit": unit, "quote": text}]))
        self.assertEqual(ep.status()["location"]["short"], "Ward 6")
        self.assertTrue(entry["lines"][0]["late"])

    def test_future_completed_event_is_withheld_from_current_state(self):
        text = "The hip surgery was completed on October 20"
        ep, entry = self.entry(text, [{"type": "procedure_done", "what": "Hip surgery", "quote": text}], kind="recording")
        self.assertFalse(entry["lines"][0]["applied"])
        self.assertEqual(ep.status()["procedures"], [])
        self.assertEqual(entry["event_time"]["status"], "pending_confirmation")

    def test_latest_valid_family_plan_and_withdrawal_survive_source_revision(self):
        ep = Episode(SCENARIO)
        for uid, at, text in (("p1", "2026-10-17T09:00:00+01:00", "I'll be there on October 20 afternoon"),
                              ("p2", "2026-10-17T10:00:00+01:00", "I can't come on October 20 afternoon")):
            ep.add_update(upd(uid, at, "note", text,
                              [{"type": "family", "what": "Family will be there", "quote": text}], topic="plan"))
        self.assertEqual(ep.plans()[0]["update_id"], "p2")
        self.assertEqual(ep.plans()[0]["plan_status"], "withdrawn")
        self.assertIn("can't come", ep.entries[-1]["facts"][0]["what"])
        ep.delete_update("p2", expected_revision=1, request_id="remove-plan")
        self.assertEqual(ep.plans()[0]["update_id"], "p1")

    def test_new_plan_replaces_legacy_future_source_clock_and_can_move_earlier(self):
        ep = Episode(SCENARIO)
        for uid, at, text in (("c01", "2026-10-19T08:00:00+01:00", "I'll be there on 10/20 afternoon"),
                              ("new", "2026-10-17T10:00:00+01:00", "I'll be there on 10/21 afternoon"),
                              ("earlier", "2026-10-17T10:01:00+01:00", "I'll be there on 10/20 afternoon")):
            ep.add_update(upd(uid, at, "note", text, [], topic="plan"))
            self.assertEqual(ep.plans()[0]["update_id"], uid)
        self.assertEqual(ep.plans()[0]["event_time"]["when"], "2026-10-20")

    def test_unknown_conflicting_state_dates_require_confirmation(self):
        ep = Episode(SCENARIO)
        for uid, unit in (("one", "Ward 5"), ("two", "Ward 6")):
            text = "She is in " + unit
            entry = ep.add_update(upd(uid, "2026-10-17T10:00:00+01:00", "recording", text,
                                     [{"type": "location", "unit": unit, "quote": text}]))
        self.assertFalse(entry["lines"][0]["applied"])
        state = ep.status()["location"]
        self.assertTrue(state["time_uncertain"])
        self.assertEqual(state["uncertain_alternatives"][0]["fact"]["unit"], "Ward 6")

    def test_explicit_foreign_timezone_and_future_completed_family_stay_pending(self):
        for text in ("I'll arrive 10/20 at 14:30 Toronto time", "I arrived on 10/20 afternoon",
                     "I'll arrive on 2026-10-20 at 15:00 UTC.", "I haven't arrived on October 16",
                     "I'll arrive on 20 October 2026 at 9am Tokyo time.",
                     "I'll arrive on 20 October 2026 at 9am New York time."):
            _, entry = self.entry(text)
            self.assertEqual(entry["event_time"]["status"], "pending_confirmation")

    def test_late_discharge_does_not_override_a_later_admission_event(self):
        ep = Episode(SCENARIO)
        for uid, source_at, text, facts in (
                ("admit", "2026-10-17T09:00:00+01:00", "She was admitted to Ward 6 on October 17", [
                    {"type": "admitted", "quote": "She was admitted to Ward 6 on October 17"},
                    {"type": "location", "unit": "Ward 6", "quote": "She was admitted to Ward 6 on October 17"}]),
                ("old-discharge", "2026-10-17T10:00:00+01:00", "She was discharged on October 16", [
                    {"type": "discharged", "quote": "She was discharged on October 16"}])):
            ep.add_update(upd(uid, source_at, "recording", text, facts))
        self.assertIsNone(ep.status()["discharged"])
        self.assertEqual(ep.status()["location"]["short"], "Ward 6")

    def test_readmission_event_closes_discharge_despite_earlier_source_clock(self):
        ep = Episode(SCENARIO)
        for uid, source_at, text, fact in (
                ("left", "2026-10-17T11:00:00+01:00", "She was discharged on October 16",
                 {"type": "discharged"}),
                ("readmit", "2026-10-17T09:00:00+01:00", "She was admitted on October 17",
                 {"type": "admitted"})):
            ep.add_update(upd(uid, source_at, "recording", text, [{**fact, "quote": text}]))
        self.assertIsNone(ep.status()["discharged"])
        self.assertEqual(ep.phase(), "Admitted to hospital")

    def test_future_location_plan_does_not_become_current_location(self):
        text = "She will move to Ward 6 on October 20"
        ep, entry = self.entry(text, [{"type": "location", "unit": "Ward 6", "quote": text}], kind="recording")
        self.assertFalse(entry["lines"][0]["applied"])
        self.assertIsNone(ep.status()["location"])

    def test_undated_discharge_cannot_silently_override_dated_current_stay(self):
        ep = Episode(SCENARIO)
        text = "She was admitted on October 17"
        ep.add_update(upd("admit", "2026-10-17T09:00:00+01:00", "recording", text,
                          [{"type": "admitted", "quote": text}]))
        text = "She has been discharged"
        entry = ep.add_update(upd("unknown-discharge", "2026-10-17T10:00:00+01:00", "recording", text,
                                  [{"type": "discharged", "quote": text}]))
        self.assertFalse(entry["lines"][0]["applied"])
        self.assertIsNone(ep.status()["discharged"])
        self.assertEqual(ep.phase(), "Current patient status needs confirmation")

    def test_undated_return_to_hospital_does_not_replace_dated_discharge(self):
        for text, fact in (("She was admitted to hospital.", {"type": "admitted"}),
                           ("She is at Kingston Hospital.", {"type": "location", "hospital": "Kingston Hospital"})):
            with self.subTest(fact_type=fact["type"]):
                ep = Episode(SCENARIO)
                discharged = "Discharged home on 16 October 2026."
                ep.add_update(upd("left", "2026-10-17T09:00:00+01:00", "recording", discharged,
                                  [{"type": "discharged", "quote": discharged}]))
                entry = ep.add_update(upd("return", "2026-10-18T09:00:00+01:00", "recording", text,
                                          [{**fact, "quote": text}]))
                self.assertIsNotNone(ep.status()["discharged"])
                self.assertEqual(ep.status()["discharged"]["when"], "2026-10-16")
                self.assertTrue(ep.status()["discharged"]["time_uncertain"])
                self.assertEqual(ep.status()["discharged"]["uncertain_alternatives"][0]["fact"]["quote"], text)
                self.assertFalse(entry["lines"][0]["applied"])
                self.assertTrue(entry["lines"][0]["time_uncertain"])
                self.assertEqual(ep.phase(), "Current patient status needs confirmation")

    def test_recovery_uses_admission_event_date_instead_of_source_clock(self):
        ep = Episode(SCENARIO)
        admitted = "She was admitted on October 16"
        planned = "Hip surgery is planned for October 17 at 9 a.m."
        ep.add_update(upd("admit", "2026-10-18T09:00:00+01:00", "recording", admitted + ". " + planned,
                          [{"type": "admitted", "quote": admitted},
                           {"type": "procedure_planned", "what": "Hip surgery", "quote": planned}]))
        completed = "Hip surgery was completed on October 17"
        ep.add_update(upd("done", "2026-10-18T10:00:00+01:00", "recording", completed,
                          [{"type": "procedure_done", "what": "Hip surgery", "quote": completed}]))
        self.assertEqual(ep.phase(), "Recovering after hip surgery")

    def test_decimal_medication_dose_is_not_a_clock(self):
        text = "On 17 October 2026, start digoxin 0.25 mg daily."
        _, entry = self.entry(text, [{"type": "medication", "name": "digoxin", "dose": "0.25 mg",
                                     "status": "new", "quote": text}], kind="recording")
        self.assertEqual(entry["event_time"]["when"], "2026-10-17")
        self.assertEqual(entry["event_time"]["precision"], "date")
        _, clock_entry = self.entry("I'll arrive on 20 October 2026 at 9.30am")
        self.assertEqual(clock_entry["event_time"]["when"], "2026-10-20T09:30:00+01:00")
        self.assertEqual(clock_entry["event_time"]["precision"], "clock")

    def test_recovery_needs_admission_and_operation_event_dates(self):
        for admitted, completed in (("She was admitted to hospital", "Hip surgery was completed on October 17"),
                                    ("She was admitted on October 16", "Hip surgery was completed")):
            with self.subTest(admitted=admitted, completed=completed):
                ep = Episode(SCENARIO)
                planned = "Hip surgery is planned for October 17 at 9 a.m."
                ep.add_update(upd("admit", "2026-10-18T09:00:00+01:00", "recording", admitted + ". " + planned,
                                  [{"type": "admitted", "quote": admitted},
                                   {"type": "procedure_planned", "what": "Hip surgery", "quote": planned}]))
                ep.add_update(upd("done", "2026-10-18T10:00:00+01:00", "recording", completed,
                                  [{"type": "procedure_done", "what": "Hip surgery", "quote": completed}]))
                self.assertEqual(ep.phase(), "Current patient status needs confirmation")

    def test_same_day_coarse_admission_does_not_prove_operation_order(self):
        for suffix in (" at 10 a.m.", ""):
            with self.subTest(completed_clock=suffix):
                ep = Episode(SCENARIO)
                admitted = "She was admitted on 17 October 2026."
                planned = "Hip surgery is planned for 17 October 2026 at 9 a.m."
                ep.add_update(upd("admit", "2026-10-18T09:00:00+01:00", "recording", admitted + " " + planned,
                                  [{"type": "admitted", "quote": admitted},
                                   {"type": "procedure_planned", "what": "Hip surgery", "quote": planned}]))
                completed = "Hip surgery was completed on 17 October 2026" + suffix
                ep.add_update(upd("done", "2026-10-18T10:00:00+01:00", "recording", completed,
                                  [{"type": "procedure_done", "what": "Hip surgery", "quote": completed}]))
                self.assertEqual(ep.phase(), "Current patient status needs confirmation")


if __name__ == "__main__":
    unittest.main(verbosity=1)
