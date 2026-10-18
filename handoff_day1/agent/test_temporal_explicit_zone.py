"""Independent literal IANA/offset cases; no model, benchmark files or network."""
import copy
import datetime as dt
import hashlib
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import episode
from episode import Episode, event_time, parse_when, upgrade_episode
import timeline_html as T


def setUpModule():
    print("EXPLICIT_HOSPITAL_ZONE_20261018_V1 " + json.dumps({module.__name__: {
        "path": module.__file__, "sha256": hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()}
        for module in (episode, T)}), flush=True)


def source(text, *, zone="Europe/London", facts=None, name="Leah"):
    ep = Episode({"patient": {"name": "Nora", "timezone": zone},
                  "members": [{"member_id": "visitor", "name": name, "timezone": "America/Toronto"}],
                  "updates": []})
    proposals = facts if facts is not None else [{"type": "family", "what": text, "quote": text}]
    result = ep.add_update({"update_id": "visit", "kind": "note", "topic": "plan", "author": "visitor",
                            "at": "2029-06-01T10:00:00+00:00", "text": text}, facts=copy.deepcopy(proposals))
    if result["rejected"]:
        raise AssertionError(result["rejected"])
    return ep, result


def clock(day, zone, offset=None, time="18:20"):
    suffix = zone + (f" (UTC{offset})" if offset is not None else "")
    return f"I will arrive on {day} at {time}, {suffix}."


class ExplicitHospitalZone(unittest.TestCase):
    def pending(self, text, **options):
        ep, _ = source(text, **options)
        timing = ep.plans()[0]["event_time"]
        self.assertEqual(timing["status"], "pending_confirmation", timing)
        self.assertIsNone(timing["when"], timing)

    def test_named_family_part_of_day_actual_proposal_shape_is_one_assertion(self):
        text = "Leah will visit the patient at home on the morning of 6 June 2029, Europe/London (UTC+01:00)."
        proposal = {"type": "event", "what": "Leah will visit the patient at home", "when": "2029-06-06",
                    "when_text": "on the morning of 6 June 2029", "quote": text}
        ep, _ = source(text, facts=[proposal])
        timing = ep.plans()[0]["event_time"]
        rows = T.event_entries(ep, "visitor", "America/Toronto")
        print("INDEPENDENT_NAMED_PLAN " + json.dumps({"time": timing, "rows": len(rows)}), flush=True)
        self.assertEqual((timing["when"], timing["precision"], timing["status"]),
                         ("2029-06-06", "part_of_day", "confirmed"))
        self.assertIn("morning", T.plan_date_text(ep, ep.plans()[0]))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["lines"], [])

    def test_event_day_controls_london_summer_and_winter_offsets(self):
        for day, offset, expected in (("6 June 2029", "+01:00", "2029-06-06T18:20:00+01:00"),
                                      ("9 January 2029", "+00:00", "2029-01-09T18:20:00+00:00")):
            with self.subTest(day=day):
                ep, _ = source(clock(day, "Europe/London", offset))
                self.assertEqual(ep.plans()[0]["event_time"]["when"], expected)

    def test_hobart_summer_and_winter_use_its_configured_zone(self):
        for day, offset, expected in (("8 January 2029", "+11:00", "2029-01-08T18:20:00+11:00"),
                                      ("8 July 2029", "+10:00", "2029-07-08T18:20:00+10:00")):
            with self.subTest(day=day):
                ep, _ = source(clock(day, "Australia/Hobart", offset), zone="Australia/Hobart")
                self.assertEqual(ep.plans()[0]["event_time"]["when"], expected)

    def test_half_hour_zone_is_validated_without_rounding(self):
        ep, _ = source(clock("12 September 2029", "Asia/Kolkata", "+05:30"), zone="Asia/Kolkata")
        timing = ep.plans()[0]["event_time"]
        self.assertEqual(timing["when"], "2029-09-12T18:20:00+05:30")
        self.assertEqual(parse_when(timing["when"]).astimezone(dt.timezone.utc).strftime("%H:%M"), "12:50")

    def test_matching_iana_without_offset_keeps_clock_evidence(self):
        ep, _ = source(clock("6 June 2029", "Europe/London"))
        self.assertEqual(ep.plans()[0]["event_time"]["when"], "2029-06-06T18:20:00+01:00")

    def test_date_only_offset_never_becomes_a_clock(self):
        ep, _ = source("I will arrive on 6 June 2029, Europe/London (UTC+01:00).")
        timing = ep.plans()[0]["event_time"]
        self.assertEqual((timing["when"], timing["precision"]), ("2029-06-06", "date"))

    def test_offset_mismatches_stay_pending(self):
        for day, zone, offset in (("6 June 2029", "Europe/London", "+00:00"),
                                  ("9 January 2029", "Europe/London", "+01:00"),
                                  ("12 September 2029", "Asia/Kolkata", "+05:00")):
            with self.subTest(day=day, zone=zone):
                self.pending(clock(day, zone, offset), zone=zone)

    def test_foreign_iana_zone_is_not_treated_as_hospital_time(self):
        self.pending(clock("6 June 2029", "Asia/Kolkata", "+05:30"))
        self.pending(clock("6 June 2029", "Asia/Kolkata"))

    def test_invalid_multiple_or_malformed_zone_annotations_stay_pending(self):
        for suffix in ("Europe/NoSuchPlace", "Europe/London and Europe/Paris", "Europe/London Europe/London",
                       "Europe/London (UTC+24:00)", "Europe/London (UTC+01:75)",
                       "Europe/London (UTC+01:00) and Toronto time", "Europe/London (UTC+01:00) UTC+02:00"):
            with self.subTest(suffix=suffix):
                self.pending(f"I will arrive on 6 June 2029 at 18:20, {suffix}.")

    def test_unknown_year_missing_or_ambiguous_date_stay_pending(self):
        for target in ("on 6 June at 18:20", "at 18:20", "on tomorrow at 18:20", "on 06/07/2029 at 18:20"):
            with self.subTest(target=target):
                self.pending(f"I will arrive {target}, Europe/London (UTC+01:00).")

    def test_fold_without_offset_stays_pending(self):
        self.pending(clock("28 October 2029", "Europe/London", time="01:30"))

    def test_fold_with_unique_consistent_offset_is_disambiguated(self):
        values = []
        for offset, expected_utc in (("+01:00", "00:30"), ("+00:00", "01:30")):
            with self.subTest(offset=offset):
                ep, _ = source(clock("28 October 2029", "Europe/London", offset, time="01:30"))
                timing = ep.plans()[0]["event_time"]
                self.assertEqual(timing["when"], f"2029-10-28T01:30:00{offset}")
                values.append(parse_when(timing["when"]).astimezone(dt.timezone.utc).strftime("%H:%M"))
                self.assertEqual(values[-1], expected_utc)
        self.assertNotEqual(*values)

    def test_gap_is_not_resolved_by_an_offset(self):
        for offset in (None, "+00:00", "+01:00"):
            with self.subTest(offset=offset):
                self.pending(clock("25 March 2029", "Europe/London", offset, time="01:30"))

    def test_transition_day_part_of_day_with_offset_is_conservatively_pending(self):
        self.pending("Leah will visit the patient at home on the morning of 28 October 2029, Europe/London (UTC+00:00).")

    def test_same_source_clinical_fact_keeps_its_independent_old_date(self):
        visit = "Leah will visit the patient at home on the morning of 6 June 2029, Europe/London (UTC+01:00)."
        clinical = "Nora fell at home on 29 May 2029 at 07:40."
        ep, _ = source(clinical + " " + visit, facts=[
            {"type": "event", "what": clinical, "quote": clinical},
            {"type": "family", "what": visit, "quote": visit},
            {"type": "event", "what": "Leah will visit the patient at home", "quote": visit}])
        rows = T.event_entries(ep, "visitor", None)
        self.assertEqual(len(rows), 2)
        actual, = [row for row in rows if not T.shared_plan(row)]
        self.assertEqual([line["quote"] for line in actual["lines"]], [clinical])
        self.assertEqual(actual["event_time"]["when"], "2029-05-29T07:40:00+01:00")

    def test_mixed_clinical_quote_does_not_fold_by_visit_paraphrase(self):
        text = "Leah will visit the patient at home because Nora is unresponsive on 6 June 2029, Europe/London (UTC+01:00)."
        ep, _ = source(text, facts=[{"type": "event", "what": "Leah will visit the patient at home", "quote": text}])
        self.assertTrue(any(line["quote"] == text for row in T.event_entries(ep, "visitor", None) for line in row["lines"]))

    def test_other_actor_does_not_fold_into_authors_plan_by_theme(self):
        text = "Owen will visit the patient at home on the morning of 6 June 2029, Europe/London (UTC+01:00)."
        ep, _ = source(text, facts=[{"type": "event", "what": "Owen will visit the patient at home", "quote": text}])
        self.assertTrue(any(line["quote"] == text for row in T.event_entries(ep, "visitor", None) for line in row["lines"]))

    def test_revision_snapshot_and_live_upgrade_keep_source_versions(self):
        text = "Leah will visit the patient at home on the morning of 6 June 2029, Europe/London (UTC+01:00)."
        ep, _ = source(text, facts=[{"type": "event", "what": "Leah will visit the patient at home", "quote": text}])
        ep.revise_update("visit", {}, expected_revision=1, request_id="reaffirm")
        snapshot = ep.to_snapshot()
        restored = Episode.from_snapshot(snapshot)
        restored._temporal_projection = "source-event-time-v7"
        upgrade_episode(restored)
        self.assertEqual(restored.to_snapshot(), snapshot)
        row, = T.event_entries(restored, "visitor", None)
        self.assertEqual((row["source_revision"], row["event_time"]["when"]), (2, "2029-06-06"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
