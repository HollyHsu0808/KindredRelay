"""Owned named-arrival restatements; fresh literal inputs, no benchmark reads."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import episode
from episode import Episode, family_plan_text
import timeline_html as T


def setUpModule():
    print("NAMED_FAMILY_INTENT_20261018_V1 " + json.dumps({module.__name__: {
        "path": module.__file__, "sha256": hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()}
        for module in (episode, T)}), flush=True)


def source(text, *, quote=None, what=None, name="Avery Chen", zone="Europe/London", facts=None):
    ep = Episode({"patient": {"name": "Nora", "timezone": zone},
                  "members": [{"member_id": "visitor", "name": name}], "updates": []})
    facts = facts if facts is not None else [{"type": "event", "what": what or f"{name} will arrive",
                                            "quote": quote or text}]
    result = ep.add_update({"update_id": "plan", "kind": "note", "author": "visitor", "topic": "plan",
                            "at": "2031-01-01T09:00:00+00:00", "text": text}, facts=copy.deepcopy(facts))
    if result["rejected"]:
        raise AssertionError(result["rejected"])
    return ep, result


def generic(ep):
    return [line["quote"] for row in T.event_entries(ep, "visitor", None)
            for line in row["lines"] if line["type"] == "event"]


def clock(name="Avery Chen", target="13 January 2031 at 10:05", zone="Europe/London", offset="+00:00"):
    base = f"{name} will arrive on {target}"
    return base + f" in {zone}" + (f" (UTC{offset})" if offset is not None else "") + "."


class NamedFamilyIntent(unittest.TestCase):
    def one(self, ep):
        before, plan = ep.to_snapshot(), copy.deepcopy(ep.plans()[0])
        row, = T.event_entries(ep, "visitor", None)
        self.assertTrue(T.shared_plan(row))
        self.assertEqual(row["lines"], [])
        self.assertEqual(row["plan_status"], plan["plan_status"])
        self.assertEqual(row["event_time"], plan["event_time"])
        self.assertEqual(ep.plans()[0], plan)
        self.assertEqual(ep.to_snapshot(), before)
        return row

    def test_named_clock_with_in_zone_is_one_unchanged_plan(self):
        ep, _ = source(clock())
        row = self.one(ep)
        self.assertEqual(row["event_time"]["when"], "2031-01-13T10:05:00+00:00")

    def test_terminal_period_omission_and_half_hour_zone(self):
        text = clock("Tess Quinn", "21 August 2031 at 11:25", "Asia/Kolkata", "+05:30")
        ep, _ = source(text, quote=text[:-1], name="Tess Quinn", zone="Asia/Kolkata")
        self.assertEqual(self.one(ep)["event_time"]["when"], "2031-08-21T11:25:00+05:30")

    def test_during_part_of_day_quote_can_omit_only_complete_zone_tail(self):
        base = "Lena Eyre will arrive during the morning of 7 June 2031"
        ep, _ = source(base + " in Europe/London (UTC+01:00).", quote=base, name="Lena Eyre")
        row = self.one(ep)
        self.assertEqual((row["event_time"]["when"], row["event_time"]["precision"]), ("2031-06-07", "part_of_day"))

    def test_offset_conflict_stays_pending_after_duplicate_fold(self):
        ep, _ = source(clock("Arun Vale", "19 January 2031 at 14:40", "Australia/Hobart", "+10:00"),
                       name="Arun Vale", zone="Australia/Hobart")
        row = self.one(ep)
        self.assertEqual(row["plan_status"], "pending_confirmation")
        self.assertIsNone(row["event_time"]["when"])

    def test_fold_with_arrival_label_stays_pending(self):
        text = clock("Eden Moss", "26 October 2031 at 01:30", offset=None)
        ep, _ = source(text, quote=text[:-1], what="arrival", name="Eden Moss")
        self.assertIsNone(self.one(ep)["event_time"]["when"])

    def test_pure_two_zone_qualification_does_not_select_a_zone(self):
        text = ("Noah Vale will arrive on 22 September 2031 at 10:45 in both Europe/London and Asia/Tokyo; "
                "both zones state the same local date and clock time for the same arrival.")
        ep, _ = source(text, name="Noah Vale")
        row = self.one(ep)
        self.assertEqual(row["plan_status"], "pending_confirmation")
        self.assertIsNone(row["event_time"]["when"])

    def test_ambiguous_calendar_stays_pending(self):
        ep, _ = source(clock(target="03/04/2031 at 10:05", offset="+01:00"))
        self.assertIsNone(self.one(ep)["event_time"]["when"])

    def test_quote_before_date_or_partial_zone_tail_is_retained(self):
        text = clock()
        for quote in ("Avery Chen will arrive", text.split(" in ")[0] + " in Europe/London"):
            with self.subTest(quote=quote):
                ep, _ = source(text, quote=quote)
                self.assertEqual(generic(ep), [quote])

    def test_short_quote_cannot_override_pending_full_source_time(self):
        text = clock(target="13 January 2031 at 10:05", offset="+01:00")
        quote = text.split(" in ")[0]
        ep, _ = source(text, quote=quote)
        self.assertEqual(ep.plans()[0]["plan_status"], "pending_confirmation")
        self.assertEqual(generic(ep), [quote])
        self.assertIsNone(ep.plans()[0]["event_time"]["when"])

    def test_other_actor_and_nonliteral_paraphrase_are_retained(self):
        for text, what in ((clock("Owen Dale"), "Owen Dale will arrive"),
                           (clock(), "Avery Chen will arrive to provide wound care")):
            with self.subTest(text=text, what=what):
                ep, _ = source(text, what=what)
                self.assertEqual(generic(ep), [text])

    def test_multiple_actors_in_one_source_are_retained(self):
        text = clock()[:-1] + " and Owen Dale will arrive too."
        ep, _ = source(text)
        self.assertEqual(generic(ep), [text])

    def test_independent_clinical_tail_and_multisentence_source_are_retained(self):
        text = clock()
        for mixed in (text[:-1] + " because Nora has severe pain.",
                      text + " Nora has severe pain."):
            with self.subTest(mixed=mixed):
                ep, _ = source(mixed, quote=mixed)
                self.assertEqual(generic(ep), [mixed])
        clinical = "Nora was unresponsive on 12 January 2031 at 08:40."
        ep, _ = source(text + " " + clinical, facts=[
            {"type": "family", "what": text, "quote": text},
            {"type": "event", "what": "Avery Chen will arrive", "quote": text},
            {"type": "event", "what": clinical, "quote": clinical}])
        self.assertIn(clinical, generic(ep))
        self.assertIn(text, generic(ep))

    def test_two_zone_clause_with_another_assertion_is_retained(self):
        text = ("Avery Chen will arrive on 13 January 2031 at 10:05 in both Europe/London and Asia/Tokyo; "
                "Nora has severe pain.")
        ep, _ = source(text)
        self.assertEqual(generic(ep), [text])

    def test_repeated_quote_or_raw_question_is_not_a_closed_source(self):
        text = clock()
        for full, quote in ((text + " " + text, text), (text[:-1] + "?", text[:-1] + "?")):
            with self.subTest(full=full):
                ep, _ = source(full, quote=quote)
                self.assertEqual(generic(ep), [quote])

    def test_current_source_revision_and_update_identity_are_required(self):
        ep, entry = source(clock())
        for changes in ({"source_revision": 2}, {"update_id": "other"}):
            with self.subTest(changes=changes):
                candidate = {**entry, **changes}
                self.assertFalse(T._family_plan_supplement(ep, candidate, candidate["lines"][0], family_plan_text(candidate)))

    def test_time_mismatch_is_retained_without_borrowing_plan_clock(self):
        ep, entry = source(clock())
        real = T.event_time(ep, entry, entry["lines"][0])
        with patch.object(T, "event_time", return_value={**real, "when": "2031-01-13T10:10:00+00:00"}):
            self.assertFalse(T._family_plan_supplement(ep, entry, entry["lines"][0], family_plan_text(entry)))
        self.assertEqual(ep.plans()[0]["event_time"]["when"], "2031-01-13T10:05:00+00:00")

    def test_revision_snapshot_preserves_facts_and_full_source(self):
        ep, _ = source(clock())
        new = clock(target="14 January 2031 at 11:15")
        ep.revise_update("plan", {"text": new}, expected_revision=1, request_id="new-arrival",
                         facts=[{"type": "event", "what": "Avery Chen will arrive", "quote": new}])
        before = ep.to_snapshot()
        restored = Episode.from_snapshot(before)
        row = self.one(restored)
        self.assertEqual(row["source_revision"], 2)
        self.assertEqual(row["event_time"]["when"], "2031-01-14T11:15:00+00:00")
        self.assertEqual(restored.to_snapshot(), before)
        self.assertEqual(len(restored.entries[0]["facts"]), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
