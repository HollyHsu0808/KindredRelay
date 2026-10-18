"""Same-quote readmission supplement only; no location deduplication policy."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import episode
from episode import Episode, event_time
import timeline_html as T

SCENARIO = {"patient": {"name": "Nora", "home": "at home", "timezone": "Europe/London"},
            "members": [{"member_id": "alex", "name": "Alex"}], "updates": []}
READMIT = "Nora was readmitted to hospital on 18 November 2029 at 12:00."
LOCATION = "She is currently back in hospital."


def setUpModule():
    print("READMISSION_SAME_ASSERTION_20261018_V1 " + json.dumps({module.__name__: {
        "path": module.__file__, "sha256": hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()}
        for module in (episode, T)}), flush=True)


def add(ep, uid, text, facts):
    result = ep.add_update({"update_id": uid, "kind": "recording", "speaker_type": "care_team",
                            "speaker": "Nurse Gray", "author": "alex", "at": "2029-11-18T16:00:00+00:00",
                            "text": text}, facts=copy.deepcopy(facts))
    if result["rejected"]:
        raise AssertionError(result["rejected"])
    return result


def proposals(quote=READMIT, what="readmitted to hospital"):
    return [{"type": "event", "what": what, "quote": quote}, {"type": "admitted", "quote": quote}]


def rows(ep):
    return T.event_entries(ep, "alex", "Europe/London")


def generic_quotes(ep):
    return [line["quote"] for row in rows(ep) for line in row["lines"] if line["type"] == "event"]


class ReadmissionProjection(unittest.TestCase):
    def test_exact_literal_alias_folds_into_typed_admission_only(self):
        ep = Episode(SCENARIO)
        add(ep, "return", READMIT, proposals())
        row, = rows(ep)
        self.assertEqual([line["type"] for line in row["lines"]], ["admitted"])
        self.assertEqual(row["event_time"]["when"], "2029-11-18T12:00:00+00:00")
        self.assertIn("readmitted to hospital", row["headline"])
        self.assertEqual(len(ep.entries[0]["facts"]), 2)

    def test_discharge_and_distinct_untimed_location_remain(self):
        ep = Episode(SCENARIO)
        discharge = "Nora was discharged home on 18 November 2029 at 11:30."
        add(ep, "left", discharge, [{"type": "discharged", "quote": discharge}])
        add(ep, "return", READMIT + " " + LOCATION,
            proposals() + [{"type": "location", "hospital": "hospital", "quote": LOCATION}])
        before = ep.to_snapshot()
        projected = rows(ep)
        self.assertEqual(generic_quotes(ep), [])
        self.assertEqual({line["type"] for row in projected for line in row["lines"]},
                         {"discharged", "admitted", "location"})
        old, = [row for row in projected if any(line["type"] == "discharged" for line in row["lines"])]
        self.assertEqual(old["event_time"]["when"], "2029-11-18T11:30:00+00:00")
        location, = [row for row in projected if any(line["type"] == "location" for line in row["lines"])]
        self.assertIsNone(location["event_time"]["when"])
        self.assertEqual(location["event_time"]["source_quote"], LOCATION)
        self.assertEqual(ep.to_snapshot(), before)

    def test_negation_and_uncertainty_are_not_a_simple_readmission_assertion(self):
        for text in (READMIT.replace("was readmitted", "was not readmitted"),
                     READMIT.replace("was readmitted", "may have been readmitted"),
                     READMIT[:-1] + "?", READMIT[:-1] + " if a bed is available."):
            with self.subTest(text=text):
                ep = Episode(SCENARIO)
                add(ep, "uncertain", text, proposals(text))
                self.assertEqual(generic_quotes(ep), [text])

    def test_other_person_or_other_person_paraphrase_is_retained(self):
        for quote, what in ((READMIT.replace("Nora", "Owen"), "readmitted to hospital"),
                            (READMIT, "Owen was readmitted to hospital")):
            with self.subTest(quote=quote, what=what):
                ep = Episode(SCENARIO)
                add(ep, "other", quote, proposals(quote, what))
                self.assertEqual(generic_quotes(ep), [quote])

    def test_clinical_tail_is_retained(self):
        for tail in (" and has severe pain.", " because of bleeding.", " and then moved to Ward 4."):
            with self.subTest(tail=tail):
                text = READMIT[:-1] + tail
                ep = Episode(SCENARIO)
                add(ep, "mixed", text, proposals(text))
                self.assertEqual(generic_quotes(ep), [text])

    def test_new_location_with_distinct_quote_keeps_its_own_time(self):
        ep = Episode(SCENARIO)
        moved = "She moved to Ward 4 on 18 November 2029 at 13:15."
        add(ep, "return", READMIT + " " + moved,
            proposals() + [{"type": "location", "unit": "Ward 4", "quote": moved}])
        location, = [row for row in rows(ep) if any(line["type"] == "location" for line in row["lines"])]
        self.assertEqual(location["event_time"]["when"], "2029-11-18T13:15:00+00:00")

    def test_different_quote_and_clock_are_not_folded(self):
        ep = Episode(SCENARIO)
        other = READMIT.replace("12:00", "12:05")
        add(ep, "return", READMIT + " " + other,
            [{"type": "event", "what": "readmitted to hospital", "quote": other},
             {"type": "admitted", "quote": READMIT}])
        self.assertEqual(generic_quotes(ep), [other])
        self.assertEqual({row["event_time"]["when"] for row in rows(ep)},
                         {"2029-11-18T12:00:00+00:00", "2029-11-18T12:05:00+00:00"})

    def test_same_quote_timing_mismatch_guard_remains(self):
        ep = Episode(SCENARIO)
        entry = add(ep, "return", READMIT, proposals())
        generic, typed = entry["lines"]
        own = event_time(ep, entry, generic)
        other = {**event_time(ep, entry, typed), "when": "2029-11-18T12:05:00+00:00"}
        with patch.object(T, "event_time", side_effect=[own, other]) as timing:
            self.assertFalse(T._clinical_event_supplement(ep, entry, generic))
            self.assertEqual(timing.call_count, 2)

    def test_identical_quote_in_another_source_is_not_cross_source_deduplicated(self):
        ep = Episode(SCENARIO)
        add(ep, "generic", READMIT, proposals()[:1])
        add(ep, "typed", READMIT, proposals()[1:])
        self.assertEqual(generic_quotes(ep), [READMIT])

    def test_overbroad_substring_or_repeated_source_is_not_folded(self):
        for text, what in ((READMIT, "Noted: readmitted to hospital"),
                           (READMIT, "readmitted to hospital admission"),
                           (READMIT.replace("readmitted", "prereadmitted"), "readmitted to hospital"),
                           (READMIT + " " + READMIT, "readmitted to hospital")):
            with self.subTest(text=text, what=what):
                ep = Episode(SCENARIO)
                quote = READMIT if text == READMIT + " " + READMIT else text
                add(ep, "return", text, proposals(quote, what))
                self.assertEqual(generic_quotes(ep), [quote])

    def test_revision_uses_current_quotes_and_keeps_journal(self):
        ep = Episode(SCENARIO)
        add(ep, "return", READMIT, proposals())
        new = READMIT.replace("12:00", "12:10")
        ep.revise_update("return", {"text": READMIT + " " + new}, expected_revision=1, request_id="split-quotes",
                         facts=[{"type": "event", "what": "readmitted to hospital", "quote": READMIT},
                                {"type": "admitted", "quote": new}])
        self.assertEqual(generic_quotes(ep), [READMIT])
        ep.revise_update("return", {"text": new}, expected_revision=2, request_id="match-new", facts=proposals(new))
        before = ep.to_snapshot()
        restored = Episode.from_snapshot(before)
        row, = rows(restored)
        self.assertEqual(row["source_revision"], 3)
        self.assertEqual(row["event_time"]["when"], "2029-11-18T12:10:00+00:00")
        self.assertEqual(restored.to_snapshot(), before)
        self.assertEqual(len(restored.entries[0]["facts"]), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
