"""Narrow hospital-context London alias; literal proposals, no network or model."""
import copy
import datetime as dt
import hashlib
import json
from pathlib import Path
import sys
import unittest
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
import episode
from episode import Episode, event_time, parse_when, upgrade_episode
import timeline_html as T

TEXT = "I will arrive on October 22, 2026 at 18:00 London time."


def setUpModule():
    print("HOSPITAL_LONDON_ALIAS_20261018_V1 " + json.dumps({module.__name__: {
        "path": module.__file__, "sha256": hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()}
        for module in (episode, T)}), flush=True)


def source(text=TEXT, *, home="Europe/London", facts=None):
    ep = Episode({"patient": {"name": "Elena", "timezone": home},
                  "members": [{"member_id": "david", "name": "David", "timezone": "America/Toronto"}],
                  "updates": []})
    proposals = facts if facts is not None else [{"type": "family", "what": text, "quote": text}]
    entry = ep.add_update({"update_id": "arrival", "kind": "note", "topic": "plan", "author": "david",
                           "at": "2026-10-17T12:00:00+01:00", "text": text}, facts=copy.deepcopy(proposals))
    if entry["rejected"]:
        raise AssertionError(entry["rejected"])
    return ep, entry


class HospitalLondonAlias(unittest.TestCase):
    def test_reported_exact_plan_uses_hospital_zone_despite_toronto_viewer(self):
        ep, entry = source()
        timing = ep.plans()[0]["event_time"]
        print("LITERAL_LONDON_PLAN " + json.dumps(timing), flush=True)
        self.assertEqual((timing["when"], timing["precision"], timing["status"]),
                         ("2026-10-22T18:00:00+01:00", "clock", "confirmed"))
        self.assertEqual(timing["source_quote"], TEXT)
        self.assertEqual(timing["timezone_alias"], "Europe/London")
        self.assertEqual(parse_when(timing["when"]).astimezone(dt.timezone.utc).hour, 17)
        self.assertEqual(parse_when(timing["when"]).astimezone(ZoneInfo("America/Toronto")).hour, 13)

    def test_offset_comes_from_event_day_across_dst_boundary(self):
        for day, expected, utc_hour in ((22, "+01:00", 17), (26, "+00:00", 18)):
            with self.subTest(day=day):
                ep, _ = source(TEXT.replace("22,", f"{day},"))
                timing = ep.plans()[0]["event_time"]
                self.assertEqual(timing["when"], f"2026-10-{day}T18:00:00{expected}")
                self.assertEqual(parse_when(timing["when"]).astimezone(dt.timezone.utc).hour, utc_hour)

    def test_dst_fall_fold_and_spring_gap_stay_unknown(self):
        for text in ("I will arrive on October 25, 2026 at 01:30 London time.",
                     "I will arrive on March 29, 2026 at 01:30 London time."):
            with self.subTest(text=text):
                ep, _ = source(text)
                timing = ep.plans()[0]["event_time"]
                self.assertIsNone(timing["when"])
                self.assertEqual(timing["status"], "pending_confirmation")

    def test_matching_zone_is_required(self):
        for home in ("America/Toronto", "UTC", "Europe/Paris"):
            with self.subTest(home=home):
                ep, _ = source(home=home)
                self.assertIsNone(ep.plans()[0]["event_time"]["when"])

    def test_other_or_ambiguous_named_places_remain_unknown(self):
        for zone in ("Toronto time", "Tokyo time", "New York time", "London Ontario time",
                     "London, Ontario time", "London time (Ontario)", "London time, Canada"):
            with self.subTest(zone=zone):
                ep, _ = source(TEXT.replace("London time", zone))
                self.assertIsNone(ep.plans()[0]["event_time"]["when"])

    def test_contradictory_offset_or_zone_does_not_get_removed(self):
        for suffix in (" London time and Toronto time.", " London time UTC.",
                       "+00:00 London time.", "+01:00 London time.", "Z London time."):
            with self.subTest(suffix=suffix):
                ep, _ = source("I will arrive on October 22, 2026 at 18:00" + suffix)
                self.assertIsNone(ep.plans()[0]["event_time"]["when"])

    def test_missing_or_ambiguous_calendar_does_not_borrow_upload_date(self):
        for text in ("I will arrive at 18:00 London time.",
                     "I will arrive on 10/11/2026 at 18:00 London time.",
                     "I will arrive on October 22 or 23, 2026 at 18:00 London time."):
            with self.subTest(text=text):
                ep, _ = source(text)
                self.assertIsNone(ep.plans()[0]["event_time"]["when"])

    def test_alias_does_not_establish_an_hour_when_only_date_is_stated(self):
        ep, _ = source("I will arrive on October 22, 2026 London time.")
        timing = ep.plans()[0]["event_time"]
        self.assertEqual((timing["when"], timing["precision"]), ("2026-10-22", "date"))

    def test_clinical_explicit_zone_keeps_existing_conservative_contract(self):
        text = "Elena was admitted on October 16, 2026 at 18:00 London time."
        ep, entry = source(text, facts=[{"type": "admitted", "quote": text}])
        timing = event_time(ep, entry, entry["lines"][0])
        self.assertIsNone(timing["when"])
        self.assertEqual(timing["status"], "pending_confirmation")

    def test_independent_clinical_assertion_keeps_its_own_old_event_clock(self):
        actual = "Elena fell at home on October 16, 2026 at 08:20."
        ep, entry = source(actual + " " + TEXT, facts=[
            {"type": "event", "what": actual, "quote": actual},
            {"type": "family", "what": TEXT, "quote": TEXT}])
        rows = T.event_entries(ep, "david", "America/Toronto")
        clinical, = [row for row in rows if not T.shared_plan(row)]
        self.assertEqual(clinical["event_time"]["when"], "2026-10-16T08:20:00+01:00")
        self.assertEqual(ep.plans()[0]["event_time"]["when"], "2026-10-22T18:00:00+01:00")

    def test_literal_generic_arrival_restatement_is_one_source_assertion(self):
        ep, _ = source(facts=[{"type": kind, "what": TEXT, "quote": TEXT} for kind in ("family", "event")])
        rows = T.event_entries(ep, "david", "America/Toronto")
        print("LITERAL_LONDON_ROWS " + json.dumps([{"headline": row["headline"], "time": row["event_time"],
            "fact_ids": [line["fact"]["fact_id"] for line in row["lines"]]} for row in rows]), flush=True)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["event_time"]["when"], "2026-10-22T18:00:00+01:00")

    def test_snapshot_revision_and_live_upgrade_preserve_source_journal(self):
        ep, _ = source()
        ep.revise_update("arrival", {}, expected_revision=1, request_id="reaffirm-arrival")
        snapshot = ep.to_snapshot()
        restored = Episode.from_snapshot(snapshot)
        restored._temporal_projection = "source-event-time-v6"
        self.assertIs(upgrade_episode(restored), restored)
        self.assertEqual(restored.to_snapshot(), snapshot)
        self.assertEqual(restored.plans()[0]["source_revision"], 2)
        self.assertEqual(restored.plans()[0]["event_time"]["when"], "2026-10-22T18:00:00+01:00")


if __name__ == "__main__":
    unittest.main(verbosity=2)
