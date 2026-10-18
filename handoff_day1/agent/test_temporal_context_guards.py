"""Portable conservative temporal guards transferred from the reviewed dev repair."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parent))
import episode
from episode import Episode, event_time
from timeline_html import event_entries
SCENARIO = {"patient": {"name": "Taylor", "home": "at home", "timezone": "Europe/London"}, "members": [{"member_id": "relative", "name": "Alex", "timezone": "Europe/London"}], "updates": []}

def source_entry(text, quote=None, *, kind="photo", fact_type="admitted", revision=1):
    ep = Episode(SCENARIO)
    fact = {"type": fact_type, "quote": quote or text}
    if fact_type == "family":
        fact["what"] = "Family plan"
    if fact_type == "location":
        fact["hospital"] = "River Hospital"
    update = {"update_id": "source", "at": "2026-11-29T12:00:00+00:00", "kind": kind,
              "author": "relative", "text": text, "source_revision": revision}
    if fact_type == "family":
        update["topic"] = "plan"
    return ep, update, fact



class SourceContextGuards(unittest.TestCase):
    def test_another_assertions_day_and_clock_do_not_date_admission(self):
        header = "Admission sheet, dated 17 November 2026: "
        for clause, short in (
                ("Taylor was admitted to River Hospital last week and the sheet was reviewed at 08:20 that day",
                 "Taylor was admitted to River Hospital last week"),
                ("Taylor was admitted to River Hospital, but the sheet was reviewed at 08:20 that day",
                 "Taylor was admitted to River Hospital"),
                ("Taylor was admitted to River Hospital and Alex was reviewed at 08:20 that day",
                 "Taylor was admitted to River Hospital"),
                ("Taylor was admitted to River Hospital at 08:20 that day, actually on 18 November 2026",
                 "Taylor was admitted to River Hospital at 08:20 that day"),
                ("Taylor was admitted to River Hospital at 08:20 that day at 09:20",
                 "Taylor was admitted to River Hospital at 08:20 that day")):
            for quote in (short, clause, header + clause):
                with self.subTest(clause=clause, quote=quote):
                    ep, update, fact = source_entry(header + clause + ".", quote)
                    timing = event_time(ep, update, {"fact": fact})
                    self.assertEqual((timing["when"], timing["status"]), (None, "pending_confirmation"))

    def test_entity_and_is_supported_but_clinical_tail_needs_confirmation(self):
        quote = "Taylor was admitted to River and Valley Hospital"
        text = "Admission sheet, dated 17 November 2026: " + quote + " at 08:20 that day."
        ep, update, fact = source_entry(text, quote)
        timing = event_time(ep, update, {"fact": fact})
        self.assertEqual((timing["when"], timing["status"]), ("2026-11-17T08:20:00+00:00", "confirmed"))
        update["text"] = text[:-1] + " and rested comfortably."
        timing = event_time(ep, update, {"fact": fact})
        self.assertEqual((timing["when"], timing["status"]), (None, "pending_confirmation"))

    def test_linked_part_of_day_keeps_descriptor_with_a_short_quote(self):
        quote = "Taylor was admitted to River Hospital"
        text = "Admission sheet, dated 17 November 2026: " + quote + " in the afternoon that day."
        ep, update, fact = source_entry(text, quote)
        timing = event_time(ep, update, {"fact": fact})
        self.assertEqual((timing["when"], timing["precision"], timing["status"]),
                         ("2026-11-17", "part_of_day", "confirmed"))
        self.assertIn("afternoon", timing["when_text"])
        self.assertEqual(timing["source_quote"], quote)
        self.assertEqual(timing["source_context"]["quote"], text[:-1])

    def test_header_link_supports_short_quote_and_record_recalculation(self):
        clause = "Taylor was admitted to River Hospital at 08:20 that day"
        text = "Admission sheet, dated 17 November 2026: " + clause + "."
        ep, update, fact = source_entry(text, "Taylor was admitted to River Hospital", fact_type="location")
        ep.add_update(update, facts=[fact])
        rec = ep.slots["location"]
        self.assertEqual(event_time(ep, rec, {"fact": rec["fact"]})["when"], "2026-11-17T08:20:00+00:00")
        self.assertEqual(rec["event_time"]["source_context"]["quote"], text[:-1])
        self.assertEqual(rec["fact"]["quote"], fact["quote"])

    def test_document_date_needs_same_clause_explicit_day_link(self):
        cases = [
            ("Admission sheet, dated 17 November 2026: Taylor was admitted to River Hospital at 08:20.",
             "Taylor was admitted to River Hospital at 08:20"),
            ("Admission sheet, dated 17 November 2026. Taylor was admitted to River Hospital at 08:20 that day.",
             "Taylor was admitted to River Hospital at 08:20 that day"),
            ("Admission sheet, dated 17 November: Taylor was admitted to River Hospital at 08:20 that day.",
             "Taylor was admitted to River Hospital at 08:20 that day"),
            ("Admission sheet, dated 06/07/2026: Taylor was admitted to River Hospital at 08:20 that day.",
             "Taylor was admitted to River Hospital at 08:20 that day"),
            ("Admission sheet, not dated 17 November 2026: Taylor was admitted to River Hospital at 08:20 that day.",
             "Taylor was admitted to River Hospital at 08:20 that day"),
            ("Admission sheet, dated 17 November 2026: Records were checked that day. Taylor was admitted to River Hospital at 08:20.",
             "Taylor was admitted to River Hospital at 08:20"),
            ("Admission sheet, dated 17 November 2026: Taylor was admitted to River Hospital at 08:20 that day. Taylor was admitted to River Hospital at 08:20 that day.",
             "Taylor was admitted to River Hospital at 08:20 that day"),
            ("Admission sheet, dated 17 November 2026: Taylor was admitted to River Hospital at 08:20 that day. She is resting.",
             "Admission sheet, dated 17 November 2026: Taylor was admitted to River Hospital at 08:20 that day. She is resting."),
        ]
        for text, quote in cases:
            with self.subTest(text=text):
                ep, update, fact = source_entry(text, quote)
                timing = event_time(ep, update, {"fact": fact})
                self.assertEqual((timing["when"], timing["status"]), (None, "pending_confirmation"))

    def test_invalid_or_conflicting_linked_dates_stay_pending(self):
        for header, clause in (
                ("31 November 2026", "Taylor was admitted to River Hospital at 08:20 that day"),
                ("17 November 2026", "Taylor was admitted to River Hospital on 18 November 2026 at 08:20 that day"),
                ("17 November 2026", "Taylor was admitted to River Hospital at 08:20 or 09:20 that day")):
            with self.subTest(header=header, clause=clause):
                ep, update, fact = source_entry("Admission sheet, dated " + header + ": " + clause + ".", clause)
                self.assertEqual(event_time(ep, update, {"fact": fact})["status"], "pending_confirmation")

    def test_header_with_another_date_or_timezone_needs_confirmation(self):
        quote = "Taylor was admitted to River Hospital at 08:20 that day"
        for header in ("Admission sheet written 16 November 2026, dated 17 November 2026",
                       "Admission sheet in Toronto time, dated 17 November 2026"):
            with self.subTest(header=header):
                ep, update, fact = source_entry(header + ": " + quote + ".", quote)
                self.assertEqual(event_time(ep, update, {"fact": fact})["status"], "pending_confirmation")

    def test_receipt_clock_and_model_date_do_not_supply_missing_day(self):
        text = "Taylor was admitted to River Hospital at 08:20"
        ep, update, fact = source_entry(text)
        fact["when"] = "2026-11-29T08:20:00+00:00"
        ep.add_update(update, facts=[fact])
        self.assertIsNone(ep.entries[0]["lines"][0]["fact"].get("when"))
        self.assertIsNone(event_time(ep, ep.entries[0], ep.entries[0]["lines"][0])["when"])

    def test_context_revision_and_snapshot_keep_the_matching_source(self):
        quote = "Taylor was admitted to River Hospital at 08:20 that day"
        ep, update, fact = source_entry("Admission sheet, dated 17 November 2026: " + quote + ".", quote)
        ep.add_update(update, facts=[fact])
        ep.revise_update("source", {"text": "Admission sheet, dated 18 November 2026: " + quote + "."},
                         expected_revision=1, request_id="correct-date", facts=[fact])
        restored = Episode.from_snapshot(ep.to_snapshot())
        rec = restored.slots["admitted"]
        timing = event_time(restored, rec, {"fact": rec["fact"]})
        self.assertEqual(timing["when"], "2026-11-18T08:20:00+00:00")
        self.assertEqual(timing["source_context"]["source_revision"], 2)
        self.assertNotIn("17 November", timing["source_context"]["quote"])
        restored.delete_update("source", expected_revision=2, request_id="delete-corrected-date")
        self.assertEqual(restored.slots, {})


class ReplacementPlanGuards(unittest.TestCase):
    def timing(self, text):
        ep, update, fact = source_entry(text, kind="note", fact_type="family")
        ep.add_update(update, facts=[fact])
        return ep.plans()[0]["event_time"]

    def test_replacement_can_move_earlier_and_uses_only_new_part_of_day(self):
        for text, day, part in (
                ("Change of plan: I will come on 4 December 2026 in the afternoon instead of 6 December in the morning.", "2026-12-04", "afternoon"),
                ("I will arrive on 6 December 2026 in the morning instead of 4 December in the afternoon.", "2026-12-06", "morning")):
            with self.subTest(text=text):
                timing = self.timing(text)
                self.assertEqual((timing["when"], timing["precision"], timing["status"]), (day, "part_of_day", "confirmed"))
                self.assertIn(part, timing["when_text"])
                self.assertEqual(timing["source_quote"], text)

    def test_real_alternatives_and_unclear_intent_stay_pending(self):
        for text in (
                "I will come on 4 December 2026 or 2 December.",
                "I might come on 4 December 2026 instead of 2 December.",
                "If the train runs, I will come on 4 December 2026 instead of 2 December.",
                "I will come on 4 December 2026 instead of 2 December?",
                "I will not come on 4 December 2026 instead of 2 December.",
                "Instead of 2 December, I will come on 4 December 2026.",
                "I will come on 4 December 2026 instead of 2 December or 6 December.",
                "I will come on 4 December 2026 instead of 2 December; I may also visit on 6 December.",
                "I will come on 4 December 2026 instead of 2 December, but the new day is not confirmed."):
            with self.subTest(text=text):
                timing = self.timing(text)
                self.assertEqual((timing["when"], timing["status"]), (None, "pending_confirmation"))

    def test_ambiguous_numeric_and_invalid_replacement_targets_stay_pending(self):
        for text in (
                "I will come on 06/07/2026 instead of 2 December.",
                "I will come on 4 December 2026 instead of 06/07/2026.",
                "I will come on 31 November 2026 instead of 2 December.",
                "I will come on 4 December 2026 instead of 31 November 2026."):
            with self.subTest(text=text):
                timing = self.timing(text)
                self.assertEqual((timing["when"], timing["status"]), (None, "pending_confirmation"))

    def test_omitted_new_year_needs_confirmation_but_explicit_new_year_stands(self):
        timing = self.timing("I will come on 4 December instead of 2 December 2027.")
        self.assertEqual((timing["when"], timing["status"]), (None, "pending_confirmation"))
        timing = self.timing("I will come on 4 December 2027 instead of 2 December.")
        self.assertEqual((timing["when"], timing["status"]), ("2027-12-04", "confirmed"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
