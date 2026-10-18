"""Offline tests of scripts/primock_gold_eval.py; every endpoint is the scripted DryTransport, nothing touches the network.

.venv/Scripts/python.exe scripts/test_primock_gold_eval.py
"""
from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import csv
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import primock_gold_eval as G  # noqa: E402

SENTINEL = "sk-SENTINEL-7f3a9c1e5b2d4f60a8e1"   # never a real key
NOTE = ("4/7 hx of generally unwell, mainly sore throat, runny nose. Initially had fever, but now settling with "
        "paracetamol 1,000 mg. \nNo chest pain. See Dr. Smith tomorrow.\n\nPMH: Nil \nDH: nil \nNKDA\n"
        "FH: Grandmother - type 2 diabetes\nSH: lives alone, works as an accountant. \n\nImp: viral URTI \n\nPlan:\n"
        "1.\tConservative mx - rest, push fluids\n2.\tReview in 5-7d INB\n"
        "3.\tDiscussed red flag sx (SOB, chest pain, fevers)- if present, for urgent review with Dr \n")


def textgrid(intervals: list[tuple[float, float, str]]) -> str:
    rows = "".join(f'        intervals [{i}]:\n            xmin = {a}\n            xmax = {b}\n            text = "{t}"\n'
                   for i, (a, b, t) in enumerate(intervals, 1))
    return ('File type = "ooTextFile"\nObject class = "TextGrid"\n\nitem []:\n    item [1]:\n        class = '
            f'"IntervalTier"\n        name = "Speaker"\n{rows}')


def make_raw(root: Path, cid: str = "day9_consultation01") -> Path:
    raw = root / "raw"
    (raw / "notes").mkdir(parents=True)
    (raw / "transcripts").mkdir()
    (raw / "notes" / f"{cid}.json").write_text(json.dumps({"note": NOTE, "presenting_complaint": "cough"}),
                                               encoding="utf-8")
    doc = [(0.0, 3.0, "Hello, how can I help you today?"), (9.0, 12.0, "Any chest pain at all?"),
           (20.0, 25.0, "Take paracetamol and rest, push fluids, and if you get short of breath call us urgently."),
           (26.0, 27.0, "<INAUDIBLE_SPEECH/>")]
    pat = [(3.5, 8.0, "I have had a sore throat and a runny nose for four days now."),
           (12.5, 15.0, "No, <UNSURE>no</UNSURE> chest pain."), (15.5, 19.0, "My grandmother has type 2 diabetes.")]
    (raw / "transcripts" / f"{cid}_doctor.TextGrid").write_text(textgrid(doc), encoding="utf-8")
    (raw / "transcripts" / f"{cid}_patient.TextGrid").write_text(textgrid(pat), encoding="utf-8")
    return raw


class Base(unittest.TestCase):
    def setUp(self):
        self._env = patch.dict(os.environ)
        self._env.start()
        for k in list(os.environ):
            if k.startswith(("CARERELAY_LLM_", "KINDRED_VERIFIER_")):
                del os.environ[k]
        self.tmp = Path(tempfile.mkdtemp(prefix="primock_gold_test_"))
        self._flag = patch.object(G, "LOAD_TEST_FLAG", self.tmp / "no_load_test")   # a real load test may be running
        self._flag.start()

    def tearDown(self):
        self._flag.stop()
        self._env.stop()

    def run_main(self, argv, **kw):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = G.main(argv, sleep=lambda s: None, **kw)
        return code, out.getvalue(), err.getvalue()


class NoteSplit(unittest.TestCase):
    def setUp(self):
        self.facts = G.split_note(NOTE)
        self.text = [f["text"] for f in self.facts]

    def test_sections_and_atomic_clauses(self):
        by = {f["text"]: f["section"] for f in self.facts}
        self.assertEqual(self.text[:3], ["4/7 hx of generally unwell", "mainly sore throat", "runny nose"])
        self.assertEqual(by["Nil"], "pmh")
        self.assertEqual(by["nil"], "medications")
        self.assertEqual(by["NKDA"], "allergies")
        self.assertEqual(by["Grandmother - type 2 diabetes"], "family_history")
        self.assertEqual(by["works as an accountant"], "social_history")
        self.assertEqual(by["viral URTI"], "impression")
        self.assertEqual(by["push fluids"], "plan")
        self.assertEqual([f["nid"] for f in self.facts], [f"N{i:02d}" for i in range(1, len(self.facts) + 1)])

    def test_numbers_abbreviations_brackets_and_conditions_are_not_split(self):
        self.assertIn("but now settling with paracetamol 1,000 mg", self.text)   # 1,000 is one number
        self.assertIn("See Dr. Smith tomorrow", self.text)                       # Dr. ends no sentence
        red = [f for f in self.facts if f["text"].startswith("Discussed red flag")]
        self.assertEqual(len(red), 1)   # brackets kept, the 'if present' clause joined to its action
        self.assertEqual(red[0]["text"], "Discussed red flag sx (SOB, chest pain, fevers)- if present, for urgent review with Dr")
        self.assertTrue(red[0]["safety_net"])

    def test_list_marks_dropped_and_safety_net_flags(self):
        self.assertIn("Review in 5-7d INB", self.text)
        flags = {f["text"]: f["safety_net"] for f in self.facts}
        self.assertTrue(flags["Review in 5-7d INB"])
        self.assertFalse(flags["push fluids"])
        self.assertFalse(flags["No chest pain"])
        self.assertEqual(G.clauses("for urgent review, if worse"), ["for urgent review, if worse"])

    def test_deterministic(self):
        self.assertEqual(G.split_note(NOTE), self.facts)
        self.assertEqual(G.split_note(NOTE.replace("\n", "\r\n")), self.facts)


class Transcript(Base):
    def test_turns_markup_and_chunks(self):
        raw = make_raw(self.tmp)
        segs = G.load_segments(raw, "day9_consultation01")
        self.assertEqual(segs[0]["segment_id"], "day9_consultation01_seg000")
        turns = G.build_turns(segs)
        self.assertEqual([t["speaker"] for t in turns], ["doctor", "patient", "doctor", "patient", "doctor"])
        self.assertEqual(turns[3]["text"], "No, no chest pain. My grandmother has type 2 diabetes.")   # merged, markup out
        self.assertFalse(any("INAUDIBLE" in t["text"] for t in turns))
        chunks = G.chunk_turns(turns, limit=120)
        self.assertEqual([t for c in chunks for t in c], turns)   # every turn once, in order
        for c in chunks:
            text = "\n".join(G.turn_line(t) for t in c)
            self.assertTrue(len(text) <= 120 or len(c) == 1)
        ups = G.make_updates("day9_consultation01", turns, limit=120)
        self.assertEqual(ups[0]["update_id"], "day9_consultation01_part01")
        self.assertTrue(ups[0]["text"].startswith("Doctor: Hello"))
        self.assertEqual(ups[0]["at"], "2026-01-05T09:00:00+00:00")

    def test_quote_speakers(self):
        text = "Doctor: Any chest pain at all?\nPatient: No, no chest pain. My grandmother has diabetes."
        self.assertEqual(G.quote_speakers("my grandmother has diabetes", text), "patient")
        self.assertEqual(G.quote_speakers("at all? Patient: No", text), "doctor+patient")
        self.assertEqual(G.quote_speakers("never said", text), "unknown")


class Labels(unittest.TestCase):
    def test_parse_labels_problems(self):
        obj = {"labels": [{"id": "N01", "label": "covered", "fact_ids": ["E01", "E99"], "why": "x"},
                          {"id": "N01", "label": "not_covered", "fact_ids": [], "why": "dup"},
                          {"id": "N02", "label": "maybe", "fact_ids": [], "why": "bad"},
                          {"id": "N77", "label": "covered", "fact_ids": [], "why": "unknown"}]}
        labels, p = G.parse_labels("A", obj, ["N01", "N02", "N03"], {"E01"})
        self.assertEqual(labels["N01"]["fact_ids"], ["E01"])
        self.assertEqual(p["duplicates"], ["N01"])
        self.assertEqual(p["invalid"], ["N02"])
        self.assertEqual(p["unknown_ids"], ["N77"])
        self.assertEqual(p["missing"], ["N02", "N03"])
        _, p = G.parse_labels("A", None, ["N01"], set())
        self.assertFalse(p["parsed"])
        self.assertEqual(p["missing"], ["N01"])

    def test_salvage_of_a_cut_off_reply(self):
        text = ('{"labels": [{"id": "N01", "label": "covered", "fact_ids": ["E01"], "why": "a {brace} inside"}, '
                '{"id": "N02", "label": "not_covered", "fact_ids": [], "why": "x"}, {"id": "N03", "label": "cov')
        obj = G.salvage_items(text)
        self.assertEqual([x["id"] for x in obj["labels"]], ["N01", "N02"])
        labels, p = G.parse_labels("A", obj, ["N01", "N02", "N03"], {"E01"})
        self.assertEqual(sorted(labels), ["N01", "N02"])
        self.assertEqual(p["missing"], ["N03"])
        self.assertIsNone(G.salvage_items("no json here"))

    def test_read_reply_salvages_a_raw_line_break_and_inner_objects(self):
        sys.path.insert(0, str(G.ROOT / "handoff_day1" / "agent"))
        from llm_client import extract_json
        text = ('{"labels": [{"id": "E01", "label": "consistent", "error_type": "none", "note_ids": ["N01"], '
                '"why": "line one\nline two"}, {"id": "E02", "label": "not_in_note", "error_type": "none", '
                '"note_ids": [], "why": "x"}]}')
        parsed = extract_json(text)   # llm_client reads one inner item of this invalid JSON, not the labels object
        self.assertFalse(isinstance(parsed, dict) and isinstance(parsed.get("labels"), list))
        labels, problems, ok = G.read_reply("B", text, parsed, "stop", ["E01", "E02"], {"N01"})
        self.assertEqual(sorted(labels), ["E01", "E02"])
        self.assertTrue(problems["salvaged"])
        self.assertFalse(ok)   # still an incomplete annotation
        good = '{"labels": [{"id": "E01", "label": "consistent", "error_type": "none", "note_ids": [], "why": "x"}]}'
        labels, problems, ok = G.read_reply("B", good, extract_json(good), "stop", ["E01"], set())
        self.assertTrue(ok)
        self.assertFalse(problems["salvaged"])
        garbled = '{"labels": [{"\u8d44": "E01", "label": "consistent", "error_type": "none", "note_ids": [], "why": "x"}]}'
        labels, problems, ok = G.read_reply("B", garbled, extract_json(garbled), "stop", ["E01"], set())
        self.assertEqual((labels, problems["unknown_ids"], ok), ({}, [""], False))   # never reinterpreted

    def test_parse_labels_error_type_coercion(self):
        obj = {"labels": [{"id": "E01", "label": "contradicts", "error_type": "none", "note_ids": ["N01"], "why": ""},
                          {"id": "E02", "label": "consistent", "error_type": "dose_number", "note_ids": [], "why": ""},
                          {"id": "E03", "label": "not_in_note", "error_type": "attribution_speaker", "note_ids": [], "why": ""}]}
        labels, p = G.parse_labels("B", obj, ["E01", "E02", "E03"], {"N01"})
        self.assertEqual(labels["E01"]["error_type"], "other_contradiction")
        self.assertEqual(labels["E02"]["error_type"], "none")
        self.assertEqual(labels["E03"]["error_type"], "attribution_speaker")
        self.assertEqual(p["coerced"], ["E01", "E02"])


class Metrics(unittest.TestCase):
    def test_omission_contradiction_dedupe_and_weights(self):
        notes = [{"nid": "N01", "section": "history", "safety_net": False}, {"nid": "N02", "section": "history", "safety_net": False},
                 {"nid": "N03", "section": "plan", "safety_net": True}, {"nid": "N04", "section": "plan", "safety_net": False}]
        la = {"N01": {"label": "covered"}, "N02": {"label": "not_covered"}, "N03": {"label": "not_covered"},
              "N04": {"label": "not_covered"}}
        lb = {"E01": {"label": "consistent", "error_type": "none", "note_ids": ["N01"]},
              "E02": {"label": "contradicts", "error_type": "negation_polarity", "note_ids": ["N02"]},
              "E03": {"label": "not_in_note", "error_type": "attribution_speaker", "note_ids": []},
              "E04": {"label": "contradicts", "error_type": "dose_number", "note_ids": []}}
        m = G.consultation_metrics(notes, [{}] * 4, la, lb, proposed=5, accepted=4)
        e = m["errors"]
        self.assertEqual((e["negation_polarity"], e["dose_number"], e["attribution_speaker"]), (1, 1, 1))
        self.assertEqual((e["omission_safety_net"], e["omission_other"]), (1, 1))   # N02 counted once, as the contradiction
        self.assertEqual(m["weighted_error"], 5 + 5 + 3 + 3 + 1)
        self.assertEqual(m["recall"], 0.25)
        self.assertEqual(m["contradiction_rate"], 0.5)
        self.assertEqual(m["grounding_pass_rate"], 0.8)
        self.assertEqual(m["recall_by_section"], {"history": [1, 2], "plan": [0, 2]})

    def test_aggregate_counts_labelled_items_of_an_incomplete_annotation(self):
        def cons(covered, labelled, ok_a, weighted):
            m = {"covered": covered, "note_facts_labelled": labelled, "contradicts": 0, "candidates_labelled": 2,
                 "not_in_note": 1, "consistent": 1, "weighted_error": weighted, "accepted": 2, "proposed": 3,
                 "safety_net_covered": 0, "safety_net_note_facts": 0, "recall_by_section": {"history": [covered, labelled]},
                 "errors": {k: 0 for k in G.ERROR_CLASSES}, "note_facts": 4}
            return {"metrics": m, "annotation_ok": {"A": ok_a, "B": True}, "parts": {"total": 1, "failed": 0,
                                                                                   "failure_classes": []}}
        agg = G.aggregate([cons(2, 4, True, 3), cons(1, 2, False, 9)])   # the second: task A labelled 2 of 4
        self.assertEqual((agg["note_fact_recall"]["num"], agg["note_fact_recall"]["den"]), (3, 6))
        self.assertEqual((agg["weighted_error_per_note_fact"]["num"], agg["weighted_error_per_note_fact"]["den"]), (3, 4))
        self.assertEqual((agg["n_annotated_A"], agg["n_both"]), (1, 1))

    def test_ratio_and_bootstrap(self):
        r = G.ratio([(1, 2), (3, 4), (0, 0)], "k")
        self.assertEqual((r["num"], r["den"], r["n_consultations"]), (4, 6, 2))
        self.assertIsNone(r["ci95"])   # n < 5: no interval
        pairs = [(i % 3, 3) for i in range(8)]
        a, b = G.ratio(pairs, "k"), G.ratio(pairs, "k")
        self.assertEqual(a["ci95"], b["ci95"])   # seeded
        self.assertLessEqual(a["ci95"][0], a["pooled"])
        self.assertLessEqual(a["pooled"], a["ci95"][1])


class Kappa(Base):
    def test_kappa_known_values(self):
        perfect = G.cohen_kappa([("covered", "covered"), ("not_covered", "not_covered")] * 3)
        self.assertEqual(perfect["kappa"], 1.0)
        # 20 rows: a says yes 10, b yes 10, agree on 7 yes + 7 no -> po .7, pe .5, kappa .4
        pairs = [("covered", "covered")] * 7 + [("covered", "not_covered")] * 3 + [("not_covered", "covered")] * 3 \
            + [("not_covered", "not_covered")] * 7
        k = G.cohen_kappa(pairs)
        self.assertEqual((k["raw_agreement"], k["expected_agreement"], k["kappa"]), (0.7, 0.5, 0.4))
        self.assertIsNone(G.cohen_kappa([("covered", "covered")] * 3)["kappa"])

    def test_kappa_csv_pending_and_filled(self):
        path = self.tmp / "human_review.csv"
        rows = [{"id": "c|note|N01", "fact": "f", "context_quote": "q", "annotator_label": "covered", "human_label": ""},
                {"id": "c|extracted|E01", "fact": "f", "context_quote": "q", "annotator_label": "not_in_note", "human_label": ""}]
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=G.HUMAN_COLUMNS)
            w.writeheader()
            w.writerows(rows)
        self.assertTrue(G.kappa_report(path)["status"].startswith("pending"))
        rows[0]["human_label"], rows[1]["human_label"] = "Not covered", "not in note"
        rows.append({"id": "c|note|N02", "fact": "f", "context_quote": "q", "annotator_label": "covered",
                     "human_label": "consistent"})   # wrong label set for a note row: invalid
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=G.HUMAN_COLUMNS)
            w.writeheader()
            w.writerows(rows)
        rep = G.kappa_report(path)
        self.assertEqual((rep["labelled"], rep["invalid_labels"]), (2, ["c|note|N02"]))
        self.assertEqual(rep["note_facts"]["raw_agreement"], 0.0)
        self.assertEqual(rep["extracted_facts"]["raw_agreement"], 1.0)
        code, out, _ = self.run_main(["kappa", "--csv", str(path)])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["labelled"], 2)


class PauseAndPrereg(Base):
    def test_pausing_transport_waits_for_the_flag(self):
        flag = self.tmp / ".load_test_running"
        flag.write_text("")
        waits = []

        def sleep(s):
            waits.append(s)
            if len(waits) == 3:
                flag.unlink()
        tr = G.PausingTransport(lambda *a, **k: "sent", flag=flag, sleep=sleep, poll_s=5, echo=lambda *a: None)
        self.assertEqual(tr("POST", "u", {}, b"", 1), "sent")
        self.assertEqual(waits, [5, 5, 5])

    def test_live_run_refuses_without_matching_preregistration(self):
        raw = make_raw(self.tmp)
        key = self.tmp / "k.txt"
        key.write_text(SENTINEL)
        missing = self.tmp / "none" / "preregistration.json"
        with patch.object(G, "PREREG", missing):
            code, _, err = self.run_main(["run", "--raw", str(raw), "--api-key-file", str(key), "--out",
                                          str(self.tmp / "o1")], transport=G.DryTransport())
        self.assertEqual(code, G.EXIT_USAGE)
        self.assertIn("run `prereg` before any live call", err)
        self.assertFalse((self.tmp / "o1").exists())
        bad = self.tmp / "preregistration.json"
        pr = {"protocol_sha256": G.B.file_sha(G.PROTOCOL), "annotation_guide_sha256": G.B.file_sha(G.GUIDE),
              "annotator_fixed_prompt_sha256": "0" * 64, "analysis_sha256": G.analysis_sha256(), "created_utc": "x"}
        bad.write_text(json.dumps(pr))
        with patch.object(G, "PREREG", bad):
            code, _, err = self.run_main(["run", "--raw", str(raw), "--api-key-file", str(key), "--out",
                                          str(self.tmp / "o2")], transport=G.DryTransport())
        self.assertEqual(code, G.EXIT_USAGE)
        self.assertIn("annotator_fixed_prompt_sha256", err)
        self.assertNotIn(SENTINEL, err)

    def test_output_path_with_token_is_refused(self):
        raw = make_raw(self.tmp)
        code, _, err = self.run_main(["run", "--dry-run", "--raw", str(raw), "--out", str(self.tmp / "my_token_dir")])
        self.assertEqual(code, G.EXIT_USAGE)
        self.assertIn("token", err)


class DryRun(Base):
    def test_end_to_end_dry_run_and_redaction(self):
        raw = make_raw(self.tmp)
        os.environ["CARERELAY_LLM_API_KEY"] = SENTINEL
        out = self.tmp / "run"
        code, stdout, err = self.run_main(["run", "--dry-run", "--raw", str(raw), "--out", str(out)])
        self.assertEqual(code, 0, err)
        self.assertEqual(sorted(p.name for p in out.iterdir()),
                         ["ATTRIBUTION.txt", "human_review.csv", "human_review_context.md", "records.jsonl",
                          "results.json", "summary.md"])
        self.assertFalse(any("token" in p.name.lower() for p in out.iterdir()))
        for p in out.iterdir():
            self.assertNotIn(SENTINEL, p.read_text(encoding="utf-8-sig"))
        res = json.loads((out / "results.json").read_text(encoding="utf-8"))
        agg = res["aggregate"]
        self.assertEqual(res["data"]["consultations_done"], 1)
        self.assertEqual(res["annotator"]["model"], G.ANNOTATORS[0][0])
        self.assertEqual(res["annotator"]["extra_body"], {"chat_template_kwargs": {"enable_thinking": False}})
        self.assertGreater(agg["facts"]["accepted"], 0)
        self.assertLess(agg["facts"]["accepted"], agg["facts"]["proposed"])   # the unquotable fact is rejected
        self.assertEqual(res["http_calls"]["by_purpose"]["annotate_A"]["calls"], 1)
        self.assertEqual(res["http_calls"]["by_purpose"]["annotate_B"]["calls"], 1)
        self.assertEqual(res["http_calls"]["by_purpose"]["models"]["calls"], 1)
        recs = G.B.read_records(out / "records.jsonl")
        ann = [r for r in recs if r["type"] == "annotation"]
        self.assertTrue(all(r["ok"] for r in ann))
        for r in ann:   # blind: no system, model or product named to the annotator
            for word in ("DeepSeek", "KindredRelay", "CareRelay", "llm_extractor", "timeline"):
                self.assertNotIn(word, r["prompt"])
        with open(out / "human_review.csv", encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
        self.assertEqual(tuple(rows[0].keys()), G.HUMAN_COLUMNS)
        n_dec = res["human_review"]["decisions_total"]
        self.assertEqual(len(rows), -(-n_dec * 2 // 10))   # ceil(20%)
        self.assertTrue(all(r["human_label"] == "" for r in rows))
        before = (out / "human_review.csv").read_bytes()
        code, _, _ = self.run_main(["report", "--out", str(out)])
        self.assertEqual(code, 0)
        self.assertEqual((out / "human_review.csv").read_bytes(), before)   # never overwritten
        # a resume of a complete run sends nothing more
        code, stdout, _ = self.run_main(["run", "--dry-run", "--resume", str(out)])
        self.assertEqual(code, 0)
        self.assertIn("1 of 1 consultations done; 0 to run", stdout)

    def test_cut_off_annotation_keeps_complete_items(self):
        class CutOff(G.DryTransport):
            def __call__(self, method, url, headers, body, timeout, stream=False):
                resp = super().__call__(method, url, headers, body, timeout, stream)
                if method == "POST" and json.loads(body)["messages"][-1]["content"].startswith("TASK B"):
                    out = json.loads(resp.body)
                    text = out["choices"][0]["message"]["content"]
                    out["choices"][0]["message"]["content"] = text[: text.index('{"id": "E02"')]
                    out["choices"][0]["finish_reason"] = "length"
                    resp = G.B.Response(200, {"Content-Type": "application/json"}, json.dumps(out).encode())
                return resp
        raw = make_raw(self.tmp)
        out = self.tmp / "run"
        code, _, err = self.run_main(["run", "--dry-run", "--raw", str(raw), "--out", str(out)], transport=CutOff())
        self.assertEqual(code, 0, err)
        recs = G.B.read_records(out / "records.jsonl")
        b = next(r for r in recs if r["type"] == "annotation" and r["task"] == "B")
        self.assertFalse(b["ok"])
        self.assertTrue(b["problems"]["salvaged"])
        self.assertEqual(list(b["labels"]), ["E01"])
        c = next(r for r in recs if r["type"] == "consultation")
        self.assertEqual(c["status"], "annotation_incomplete")
        res = json.loads((out / "results.json").read_text(encoding="utf-8"))
        self.assertEqual(res["aggregate"]["contradiction_rate"]["den"], 1)   # the one labelled item counts
        self.assertIsNone(res["aggregate"]["weighted_error_per_note_fact"]["pooled"])   # needs both tasks complete

    def test_reparse_changes_nothing_for_complete_replies(self):
        raw = make_raw(self.tmp)
        out = self.tmp / "run"
        code, _, err = self.run_main(["run", "--dry-run", "--raw", str(raw), "--out", str(out)])
        self.assertEqual(code, 0, err)
        code, stdout, err = self.run_main(["report", "--out", str(out), "--reparse"])
        self.assertEqual(code, 0, err)
        self.assertIn("changed: []", stdout)
        a = json.loads((out / "results.json").read_text(encoding="utf-8"))
        b = json.loads((out / "results_reparsed.json").read_text(encoding="utf-8"))
        self.assertEqual(a["aggregate"], b["aggregate"])

    def test_call_cap_stops_and_resume_completes(self):
        raw = make_raw(self.tmp)
        out = self.tmp / "run"
        code, stdout, _ = self.run_main(["run", "--dry-run", "--raw", str(raw), "--out", str(out), "--max-calls", "2"])
        self.assertEqual(code, G.EXIT_PARTIAL)
        self.assertFalse((out / "human_review.csv").exists())
        code, stdout, _ = self.run_main(["run", "--dry-run", "--resume", str(out), "--max-calls", "20"])
        self.assertEqual(code, 0)
        res = json.loads((out / "results.json").read_text(encoding="utf-8"))
        self.assertEqual(res["data"]["consultations_done"], 1)
        self.assertTrue((out / "human_review.csv").exists())

    def test_deadline_stops_between_consultations(self):
        raw = make_raw(self.tmp)
        out = self.tmp / "run"
        code, stdout, _ = self.run_main(["run", "--dry-run", "--raw", str(raw), "--out", str(out),
                                         "--deadline-utc", "2020-01-01T00:00:00Z"])
        self.assertEqual(code, G.EXIT_PARTIAL)
        self.assertIn("--deadline-utc", stdout)
        res = json.loads((out / "results.json").read_text(encoding="utf-8"))
        self.assertEqual((res["stopped_reason"], res["data"]["consultations_done"]), ("deadline", 0))
        code, _, err = self.run_main(["run", "--dry-run", "--raw", str(raw), "--out", str(self.tmp / "r2"),
                                      "--deadline-utc", "tomorrow"])
        self.assertEqual(code, G.EXIT_USAGE)
        self.assertFalse((self.tmp / "r2").exists())
        code, _, _ = self.run_main(["run", "--dry-run", "--resume", str(out)])   # no deadline this time: completes
        self.assertEqual(code, 0)

    def test_unreadable_transcript_is_skipped_not_scored(self):
        raw = make_raw(self.tmp)
        make_raw(self.tmp / "b", "day9_consultation02")
        for p in (self.tmp / "b" / "raw").rglob("*.*"):
            target = raw / p.relative_to(self.tmp / "b" / "raw")
            target.write_bytes(p.read_bytes())
        (raw / "transcripts" / "day9_consultation02_doctor.TextGrid").write_text("not a textgrid", encoding="utf-8")
        (raw / "transcripts" / "day9_consultation02_patient.TextGrid").write_text("not a textgrid", encoding="utf-8")
        out = self.tmp / "run"
        code, stdout, _ = self.run_main(["run", "--dry-run", "--raw", str(raw), "--out", str(out)])
        self.assertEqual(code, 0)
        res = json.loads((out / "results.json").read_text(encoding="utf-8"))
        self.assertEqual(res["data"]["consultations_done"], 1)
        self.assertEqual(res["data"]["skipped"], [{"consultation": "day9_consultation02", "reason": "no transcript turn"}])
        self.assertEqual(res["aggregate"]["n_consultations"], 1)

    def test_amendment_fixes_a_seeded_subset_and_run_follows_it(self):
        raw = make_raw(self.tmp)
        for cid in ("day9_consultation02", "day9_consultation03"):
            other = make_raw(self.tmp / cid, cid)
            for p in other.rglob("*.*"):
                (raw / p.relative_to(other)).write_bytes(p.read_bytes())
        am = self.tmp / "amendment.json"
        with patch.object(G, "AMENDMENT", am):
            code, out, err = self.run_main(["amend", "--raw", str(raw), "--subset", "2", "--deadline-utc",
                                            "2030-01-01T00:00:00Z", "--reason", "test"])
            self.assertEqual(code, 0, err)
            code, _, err = self.run_main(["amend", "--raw", str(raw), "--subset", "2", "--deadline-utc",
                                          "2030-01-01T00:00:00Z", "--reason", "again"])
            self.assertEqual(code, G.EXIT_USAGE)   # never overwritten
        obj = json.loads(am.read_text(encoding="utf-8"))
        ids = G.discover(raw)
        self.assertEqual(obj["subset"], G.processing_order(ids)[:2])
        out_dir = self.tmp / "run"
        code, _, err = self.run_main(["run", "--dry-run", "--raw", str(raw), "--amendment", str(am), "--out", str(out_dir)])
        self.assertEqual(code, 0, err)
        res = json.loads((out_dir / "results.json").read_text(encoding="utf-8"))
        self.assertEqual(res["data"]["order"], obj["subset"])
        self.assertEqual(res["data"]["consultations_done"], 2)
        self.assertEqual(res["preregistration"]["amendment"]["subset"], 2)

    def test_processing_order_is_seeded(self):
        ids = [f"day{d}_consultation{c:02d}" for d in range(1, 6) for c in range(1, 12)]
        self.assertEqual(G.processing_order(ids), G.processing_order(list(reversed(ids))))
        self.assertNotEqual(G.processing_order(ids), sorted(ids))


if __name__ == "__main__":
    unittest.main(verbosity=1)
