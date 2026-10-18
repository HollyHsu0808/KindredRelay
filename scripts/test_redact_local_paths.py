#!/usr/bin/env python3
"""Offline tests of scripts/redact_local_paths.py on synthetic files (no network, no repository data).

.venv/Scripts/python.exe scripts/test_redact_local_paths.py
Local paths are assembled at run time from a made-up profile, so this file itself passes the export's path gate.
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import redact_local_paths as R  # noqa: E402

BS = "\\"
HOME = "C:" + BS + "Us" + "ers" + BS + "alice"                 # a made-up profile, never this machine's
REPO = HOME + BS + "Documents" + BS + "Proj"
R_ = R.Redactor(HOME, REPO)


class Text(unittest.TestCase):
    def test_every_spelling_of_a_repo_path(self):
        tail = "scripts" + BS + "cases.json"
        for path in (REPO + BS + tail, REPO.replace(BS, "/") + "/scripts/cases.json",
                     "c" + REPO[1:].upper().replace("ALICE", "alice") + BS + tail,
                     "/c/" + REPO[3:].replace(BS, "/") + "/scripts/cases.json",
                     REPO.replace(BS, BS * 2) + BS * 2 + tail.replace(BS, BS * 2)):
            with self.subTest(path=path):
                self.assertEqual(R_.text(f"run {path} now"), ("run <repo>/scripts/cases.json now", 1))

    def test_outside_the_repo_keeps_only_the_last_component(self):
        key = HOME + BS + ".private" + BS + "key.txt"
        self.assertEqual(R_.text(key), ("<local>/…/key.txt", 1))
        self.assertEqual(R_.text(HOME), ("<local>", 1))
        self.assertEqual(R_.text(REPO), ("<repo>", 1))
        self.assertEqual(R_.text("`" + HOME + BS + "AppData" + BS + "x" + BS + "scratch`"), ("`<local>/…/scratch`", 1))

    def test_other_users_and_lookalikes_are_untouched(self):
        for s in ("C:" + BS + "Us" + "ers" + BS + "alicex" + BS + "a.txt", "D:" + BS + "work" + BS + "alice",
                  "release/benchmarks/x.json", "xC:" + BS + "Us" + "ers" + BS + "alice"):
            with self.subTest(s=s):
                self.assertEqual(R_.text(s), (s, 0))


class Files(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def doc(self):
        return {"cases_file": REPO + BS + "scripts" + BS + "c.json", "n": 40, "rate": 0.1, "big": 1e-05, "ok": True,
                "none": None, "argv": ["python", "--api-key-file", HOME + BS + "k" + BS + "key.txt"],
                "map": {REPO + BS + "a.py": "ab" * 32}, "f": 1.0}

    def test_json_keeps_layout_and_numbers(self):
        text = json.dumps(self.doc(), indent=1) + "\n"
        text = text.replace('"rate": 0.1', '"rate": 0.10')         # number text the producer wrote is kept
        new, facts = R.redact_bytes(text.encode(), ".json", R_)
        out = json.loads(new)
        self.assertEqual(facts["replacements"], 3)
        self.assertEqual(facts["method"], "in_place")
        self.assertIn('"rate": 0.10', new.decode())
        self.assertEqual(out["cases_file"], "<repo>/scripts/c.json")
        self.assertEqual(out["argv"][2], "<local>/…/key.txt")
        self.assertEqual(list(out["map"]), ["<repo>/a.py"])
        self.assertEqual([out[k] for k in ("n", "rate", "big", "ok", "none", "f")], [40, 0.1, 1e-05, True, None, 1.0])
        self.assertEqual(facts["values_sha256"], R.values_sha256([out]))
        self.assertNotIn("alice", new.decode())

    def test_jsonl_and_a_value_change_is_detected(self):
        lines = "".join(json.dumps({"i": i, "p": REPO + BS + f"f{i}.txt"}) + "\n" for i in range(3))
        new, facts = R.redact_bytes(lines.encode(), ".jsonl", R_)
        self.assertEqual((facts["format"], facts["replacements"]), ("jsonl", 3))
        self.assertEqual([json.loads(x)["p"] for x in new.decode().splitlines()], [f"<repo>/f{i}.txt" for i in range(3)])
        self.assertNotEqual(R.values_sha256([{"a": 1}]), R.values_sha256([{"a": 1.0}]))
        self.assertNotEqual(R.values_sha256([{"a": 1}]), R.values_sha256([{"a": True}]))
        self.assertEqual(R.values_sha256([{"a": 1, "s": "x"}]), R.values_sha256([{"a": 1, "s": "y"}]))

    def test_cli_writes_the_log_and_is_idempotent(self):
        f = self.dir / "release" / "r.json"
        f.parent.mkdir(parents=True)
        f.write_text(json.dumps(self.doc(), indent=2), encoding="utf-8")
        before = hashlib.sha256(f.read_bytes()).hexdigest()
        log = self.dir / "release" / "REDACTIONS.json"
        argv = [str(f), "--log", str(log), "--home", HOME, "--repo", str(self.dir)]
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(R.main(argv), R.EXIT_OK)
            first = json.loads(log.read_text(encoding="utf-8"))
            self.assertEqual(R.main(argv), R.EXIT_OK)          # nothing left: the entry stays as it was
        entry, = first["files"]
        self.assertEqual(entry["path"], "release/r.json")
        self.assertEqual(entry["original_sha256"], before)
        self.assertEqual(entry["redacted_sha256"], hashlib.sha256(f.read_bytes()).hexdigest())
        self.assertEqual(json.loads(log.read_text(encoding="utf-8"))["files"], first["files"])
        self.assertIn("produced before redaction", first["note"])
        md = log.with_suffix(".md").read_text(encoding="utf-8")
        self.assertIn(entry["redacted_sha256"], md)
        self.assertNotIn("alice", md + log.read_text(encoding="utf-8"))

    def test_unsafe_file_is_not_written(self):
        f = self.dir / "bad.json"
        f.write_text("{not json", encoding="utf-8")
        with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(R.main([str(f), "--log", str(self.dir / "L.json"), "--home", HOME]), R.EXIT_UNSAFE)
        self.assertEqual(f.read_text(encoding="utf-8"), "{not json")


if __name__ == "__main__":
    unittest.main(verbosity=2)
