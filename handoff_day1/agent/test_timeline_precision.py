"""Literal proposals for a reported typed-plan cancellation; no model or gold.

The observed UI did not expose its proposal JSON. These explicit proposal shapes
discriminate projection behavior; they do not claim to replay that extraction.
"""
import copy
import hashlib
import html
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import episode
from episode import Episode
import timeline_html as T


SCENARIO = {"patient": {"name": "Elena", "timezone": "Europe/London"},
            "members": [{"member_id": "anna", "name": "Anna", "timezone": "Europe/London"}],
            "updates": []}
FIRST = "I will arrive on October 20, 2026 in the afternoon."
CHANGED = "Actually, I will arrive on October 21, 2026 in the morning instead."
CANCEL = "I can no longer come on October 21, 2026. Please cancel my visit."


def setUpModule():
    print("TIMELINE_PRECISION_TYPED_CANCEL_20261017_V1 " + json.dumps({
        module.__name__: {"path": module.__file__,
                          "sha256": hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()}
        for module in (episode, T)}), flush=True)


def fact(kind, quote, what=None):
    return {"type": kind, "quote": quote, "what": what or quote}


def add(ep, uid, text, facts, *, author="anna", topic="plan", at="2026-10-17T11:00:00+01:00"):
    result = ep.add_update({"update_id": uid, "kind": "note", "author": author,
                            "topic": topic, "at": at, "text": text}, facts=copy.deepcopy(facts))
    if result["rejected"]:
        raise AssertionError(result["rejected"])
    return result


def preceding_plans():
    ep = Episode(SCENARIO)
    add(ep, "first", FIRST, [fact("family", FIRST), fact("event", FIRST)],
        at="2026-10-17T09:00:00+01:00")
    add(ep, "changed", CHANGED, [fact("family", CHANGED), fact("event", CHANGED, "Family arrival")],
        at="2026-10-17T10:00:00+01:00")
    return ep


class TypedPlanPrecision(unittest.TestCase):
    def rows(self, ep):
        return T.event_entries(ep, "anna", "Europe/London")

    def test_literal_full_cancel_quote_has_one_withdrawn_row(self):
        ep = preceding_plans()
        proposals = [fact("family", CANCEL), fact("event", CANCEL)]
        add(ep, "cancel", CANCEL, proposals)
        rows = self.rows(ep)
        print("LITERAL_CANCEL_PROJECTION " + json.dumps({"proposals": proposals, "rows": [
            {"update_id": row["update_id"], "headline": row["headline"],
             "plan_status": row.get("plan_status"), "event_time": row["event_time"],
             "fact_ids": [line["fact"]["fact_id"] for line in row["lines"]]} for row in rows]}), flush=True)
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["update_id"], rows[0]["plan_status"]), ("cancel", "withdrawn"))
        self.assertEqual(rows[0]["lines"], [])

    def test_event_only_full_cancel_quote_uses_owned_family_row(self):
        ep = preceding_plans()
        add(ep, "cancel", CANCEL, [fact("event", CANCEL)])
        row, = self.rows(ep)
        self.assertEqual(row["plan_status"], "withdrawn")

    def test_split_cancel_proposals_do_not_create_extra_cards(self):
        ep = preceding_plans()
        negative, request = CANCEL.split(". ")
        add(ep, "cancel", CANCEL, [fact("family", CANCEL), fact("event", negative + "."),
                                   fact("event", request)])
        self.assertEqual(len(self.rows(ep)), 1)

    def test_same_source_independent_clinical_assertion_keeps_its_card(self):
        clinical = "Elena fell at home on October 16, 2026 at 08:20."
        ep = preceding_plans()
        add(ep, "cancel", CANCEL + " " + clinical,
            [fact("family", CANCEL), fact("event", CANCEL), fact("event", clinical)],
            at="2026-10-23T17:00:00+01:00")
        rows = self.rows(ep)
        self.assertEqual(len(rows), 2)
        ordinary = [row for row in rows if not T.shared_plan(row)]
        self.assertEqual([line["quote"] for row in ordinary for line in row["lines"]], [clinical])
        self.assertEqual(ordinary[0]["event_time"]["when"], "2026-10-16T08:20:00+01:00")

    def test_mixed_care_quote_is_retained_even_with_visit_paraphrase(self):
        ep = preceding_plans()
        clinical = "Elena has severe pain."
        mixed = CANCEL + " " + clinical
        add(ep, "cancel", mixed, [fact("family", CANCEL), fact("event", mixed)])
        self.assertTrue(any(line["quote"] == mixed for row in self.rows(ep) for line in row["lines"]))

    def test_clinical_clause_inside_cancellation_is_not_folded(self):
        ep = preceding_plans()
        mixed = "I can no longer come on October 21, 2026 because Elena is unresponsive."
        add(ep, "cancel", mixed, [fact("family", mixed), fact("event", mixed)])
        self.assertTrue(any(line["quote"] == mixed for row in self.rows(ep) for line in row["lines"]))

    def test_cancel_target_is_not_a_cancellation_occurrence_or_upload_clock(self):
        ep = preceding_plans()
        add(ep, "cancel", CANCEL, [fact("family", CANCEL)])
        row, = self.rows(ep)
        self.assertEqual(row["event_time"]["time_role"], "withdrawal_reference")
        self.assertIsNone(row["event_time"]["when"])
        self.assertEqual(row["event_time"]["temporal_status"], "unknown")
        self.assertEqual(T.event_time_text(row["event_time"], "Europe/London"), "Cancellation time unclear")
        rendered = T.timeline_html(ep, "anna", "Europe/London")
        self.assertIn("Cancellation time unclear", rendered)
        self.assertNotIn("Wednesday 21 Oct 2026", rendered)

    def test_changed_plan_keeps_stated_date_and_part_of_day(self):
        ep = preceding_plans()
        plan, = ep.plans()
        self.assertEqual((plan["update_id"], plan["event_time"]["when"], plan["event_time"]["precision"]),
                         ("changed", "2026-10-21", "part_of_day"))
        self.assertIn("morning", T.plan_date_text(ep, plan))
        self.assertFalse(any(row["update_id"] == "first" for row in self.rows(ep)))

    def test_superseded_plan_keeps_separate_old_actual_event(self):
        ep = Episode(SCENARIO)
        actual = "Elena fell at home on October 12, 2026 at 07:45."
        add(ep, "old", actual + " " + FIRST,
            [fact("event", actual), fact("family", FIRST), fact("event", FIRST)],
            at="2026-10-17T15:00:00+01:00")
        add(ep, "changed", CHANGED, [fact("family", CHANGED)], at="2026-10-17T16:00:00+01:00")
        rows = self.rows(ep)
        old, = [row for row in rows if row["update_id"] == "old"]
        self.assertEqual([line["quote"] for line in old["lines"]], [actual])
        self.assertEqual(old["event_time"]["when"], "2026-10-12T07:45:00+01:00")

    def test_owner_and_topic_are_required_for_fold(self):
        for author, topic in (("unknown", "plan"), ("anna", None)):
            with self.subTest(author=author, topic=topic):
                ep = Episode(SCENARIO)
                add(ep, "cancel", CANCEL, [fact("event", CANCEL)], author=author, topic=topic)
                self.assertTrue(any(line["quote"] == CANCEL for row in self.rows(ep) for line in row["lines"]))

    def test_snapshot_revision_keeps_journal_and_source_evidence(self):
        ep = preceding_plans()
        add(ep, "cancel", CANCEL, [fact("family", CANCEL), fact("event", CANCEL)])
        ep.revise_update("cancel", {}, expected_revision=1, request_id="reaffirm-withdrawal")
        snapshot = ep.to_snapshot()
        restored = Episode.from_snapshot(snapshot)
        row, = self.rows(restored)
        self.assertEqual(row["source_revision"], 2)
        self.assertEqual(restored.to_snapshot(), snapshot)
        self.assertIn(html.escape(CANCEL, quote=True), T.source_archive_html(restored))
        self.assertEqual(len(restored.entries[-1]["facts"]), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
