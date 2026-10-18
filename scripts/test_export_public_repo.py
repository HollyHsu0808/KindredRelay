#!/usr/bin/env python3
"""Tests of scripts/export_public_repo.py on synthetic trees. Offline; no network, git or real secrets.

python scripts/test_export_public_repo.py
Key-like strings, CJK text and local paths are assembled at run time, so this file itself passes the export's gates.
"""
from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import export_public_repo as X  # noqa: E402

FAKE_KEY = "sk" + "-" + "Q7xR2mN8vB4kL1pZ9wT3yH6"            # looks real: no sentinel word
SENTINEL = "sk" + "-" + "SENTINEL-" + "0123456789abcdef"
GH_TOKEN = "gh" + "p_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4"
PEM = "-----BEGIN " + "RSA PRIVATE KEY-----"
ZH = chr(0x4E2D) + chr(0x6587)                            # two CJK characters
FULLWIDTH_Q = chr(0xFF1F)
LOCAL = "C:" + "\\" + "Users" + "\\" + "someone" + "\\" + "project"


def write(root: Path, rel: str, text: str | bytes) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(text, bytes):
        path.write_bytes(text)
    else:
        path.write_text(text, encoding="utf-8")


def public_dir(root: Path, manifest: str, allow: str = "") -> None:
    write(root, "public_repo/MANIFEST.txt", manifest)
    write(root, "public_repo/CJK_ALLOWLIST.txt", allow)
    for name in ("README.md", "DEPLOY.md", "EVIDENCE.md", "LICENSE"):
        write(root, "public_repo/" + name, f"{name}\n[deploy](deploy/serve.py)\n" if name.endswith(".md") else "MIT\n")


def run(argv: list[str]) -> tuple[int, str]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        code = X.main(argv)
    return code, buf.getvalue()


class TestGlob(unittest.TestCase):
    def test_double_star_spans_folders_and_single_star_does_not(self):
        self.assertTrue(X.glob_match("a/b/c.py", "a/**"))
        self.assertTrue(X.glob_match("a/c.py", "a/**/*.py"))
        self.assertTrue(X.glob_match("a/b/c/d.py", "a/**/*.py"))
        self.assertTrue(X.glob_match("x/__pycache__/m.pyc", "**/__pycache__/**"))
        self.assertFalse(X.glob_match("a/b/c.py", "a/*.py"))
        self.assertTrue(X.glob_match("deploy/test_x.py", "deploy/test_*.py"))
        self.assertFalse(X.glob_match("deploy/sub/test_x.py", "deploy/test_*.py"))

    def test_forbidden_paths(self):
        for rel in (".streamlit/secrets.toml", "data/primock/a.wav", "release/validation_abd/r/summary.json",
                    "docs/NOTES_zh-TW.md", "x/__pycache__/m.cpython-313.pyc", "desktop.ini", "deploy/prod.env",
                    ".env", "KindredRelay_Research_20261017/a.md"):
            self.assertIsNotNone(X.forbidden_reason(rel), rel)
        for rel in ("deploy/release.env.example", "handoff_day1/ui/pages/shell/data/validation.json", "README.md"):
            self.assertIsNone(X.forbidden_reason(rel), rel)

    def test_manifest_rejects_bad_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "MANIFEST.txt"
            for bad in ("deploy | a.py", "nope | a.py | why", "deploy | ../a.py | why", "deploy | /a.py | why"):
                path.write_text(bad + "\n", encoding="utf-8")
                with self.assertRaises(ValueError, msg=bad):
                    X.read_manifest(path)


class TestExport(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.root, self.out = base / "repo", base / "staging"
        write(self.root, "Dockerfile.release", "FROM python:3.12-slim\n")
        write(self.root, "deploy/serve.py", "print('serve')\n")
        write(self.root, "deploy/__pycache__/serve.cpython-313.pyc", b"\x00\x01")
        write(self.root, "docs/guide.md", "See [serve](../deploy/serve.py), [site](https://example.org) and [top](#top).\n")
        write(self.root, "README.md", "development README, not exported\n")
        write(self.root, ".streamlit/secrets.toml", 'CARERELAY_LLM_API_KEY = "' + FAKE_KEY + '"\n')

    def tearDown(self):
        self.tmp.cleanup()

    def manifest(self, *extra: str) -> str:
        lines = ["deploy | Dockerfile.release | image", "deploy | deploy/** | entry point",
                 "submission | docs/*.md | docs"] + list(extra)
        return "\n".join(lines) + "\n"

    def export(self, manifest: str, allow: str = "", *flags: str) -> tuple[int, dict]:
        public_dir(self.root, manifest, allow)
        code, _ = run(["--root", str(self.root), "--out", str(self.out), *flags])
        return code, json.loads((self.out / "EXPORT_REPORT.json").read_text(encoding="utf-8"))

    def test_clean_tree_passes_and_copies_only_the_manifest(self):
        code, report = self.export(self.manifest())
        self.assertEqual(code, 0, json.dumps(report["gates"], indent=1)[:2000])
        self.assertTrue(report["passed"])
        staged = sorted(p.relative_to(self.out).as_posix() for p in self.out.rglob("*") if p.is_file())
        self.assertEqual(staged, ["DEPLOY.md", "Dockerfile.release", "EVIDENCE.md", "EXPORT_REPORT.json", "LICENSE",
                                  "README.md", "deploy/serve.py", "docs/guide.md"])
        self.assertEqual((self.out / "README.md").read_text(encoding="utf-8").splitlines()[0], "README.md")
        self.assertIn("deploy/serve.py", report["files_sha256"])
        self.assertEqual(report["gates"]["sizes"]["files"], 7)

    def test_out_must_not_exist_and_must_be_outside_the_repository(self):
        public_dir(self.root, self.manifest())
        self.out.mkdir()
        self.assertEqual(run(["--root", str(self.root), "--out", str(self.out)])[0], 2)
        self.assertEqual(run(["--root", str(self.root), "--out", str(self.root / "inside")])[0], 2)
        self.assertFalse((self.root / "inside").exists())

    def test_secret_patterns_fail_and_sentinels_do_not(self):
        write(self.root, "deploy/config.py", f"KEY = '{FAKE_KEY}'\nTOKEN = '{GH_TOKEN}'\n{PEM}\n")
        write(self.root, "deploy/test_config.py", f"DOUBLE = '{SENTINEL}'\nid = 'fall-note-and-task-are-reviewed-x'\n")
        code, report = self.export(self.manifest())
        self.assertEqual(code, 1)
        found = {(s["path"], s["pattern"]) for s in report["gates"]["secrets"]["failing"]}
        self.assertEqual(found, {("deploy/config.py", "openai_style_key"), ("deploy/config.py", "github_token"),
                                 ("deploy/config.py", "private_key_block")})
        self.assertEqual([s["path"] for s in report["gates"]["secrets"]["sentinels"]], ["deploy/test_config.py"])
        text = (self.out / "EXPORT_REPORT.json").read_text(encoding="utf-8")
        self.assertNotIn(FAKE_KEY, text)
        self.assertNotIn(GH_TOKEN, text)

    def test_exact_key_file_counts_hits_without_printing_the_value(self):
        value = "zq" + "-live-value-9f8e7d6c5b4a"
        write(self.root, "deploy/leak.txt", f"oops {value}\n")
        key_file = Path(self.tmp.name) / "keys.toml"
        key_file.write_text(f'[section]\nAPI_KEY = "{value}"\n', encoding="utf-8")
        public_dir(self.root, self.manifest())
        code, printed = run(["--root", str(self.root), "--out", str(self.out), "--exact-key-file", str(key_file)])
        self.assertEqual(code, 1)
        report_text = (self.out / "EXPORT_REPORT.json").read_text(encoding="utf-8")
        report = json.loads(report_text)
        self.assertEqual(report["gates"]["secrets"]["exact_hits"], [{"path": "deploy/leak.txt", "occurrences": 1}])
        self.assertNotIn(value, report_text)
        self.assertNotIn(value, printed)

    def test_cjk_fails_unless_allowlisted_with_those_characters(self):
        write(self.root, "deploy/engine.py", f"STRIP = ' ?{FULLWIDTH_Q}'\n")
        write(self.root, "docs/notes.md", f"prose {ZH}\n")
        allow = f"deploy/engine.py | functional character | chars={FULLWIDTH_Q}\n"
        code, report = self.export(self.manifest(), allow)
        self.assertEqual(code, 1)
        self.assertEqual([c["path"] for c in report["gates"]["cjk"]["failing"]], ["docs/notes.md"])
        self.assertEqual([c["path"] for c in report["gates"]["cjk"]["allowlisted"]], ["deploy/engine.py"])

    def test_allowlisted_file_still_fails_on_other_characters(self):
        write(self.root, "deploy/engine.py", f"STRIP = '{FULLWIDTH_Q}'  # {ZH}\n")
        code, report = self.export(self.manifest(), f"deploy/engine.py | functional | chars={FULLWIDTH_Q}\n")
        self.assertEqual(code, 1)
        self.assertEqual(report["gates"]["cjk"]["failing"][0]["characters"], 2)

    def test_forbidden_and_generated_paths_are_refused(self):
        write(self.root, "docs/OLD_zh-TW.md", "old\n")
        code, report = self.export(self.manifest("meta | README.md | dev readme", "meta | ?.streamlit/** | never"))
        refused = {r["path"] for r in report["manifest"]["refused"]}
        self.assertEqual(refused, {"docs/OLD_zh-TW.md", "README.md"})
        # secret folders are not even walked, so a listed .streamlit/ matches nothing
        self.assertEqual(report["manifest"]["unmatched_optional"], [{"line": 5, "glob": ".streamlit/**"}])
        self.assertFalse((self.out / ".streamlit").exists())
        self.assertFalse((self.out / "docs/OLD_zh-TW.md").exists())
        self.assertEqual((self.out / "README.md").read_text(encoding="utf-8").splitlines()[0], "README.md")
        self.assertEqual(code, 0)

    def test_dangling_links_fail_and_backtick_paths_are_notices(self):
        write(self.root, "deploy/sub/x.py", "x = 1\n")
        write(self.root, "docs/guide.md", "[gone](../deploy/missing.py) [ok](../deploy/serve.py) [dir](../deploy/)\n"
                                          "[ref]: ../Dockerfile.release\n`scripts/not_exported.py:12` `deploy/serve.py`\n")
        code, report = self.export(self.manifest())
        self.assertEqual(code, 1)
        self.assertEqual([d["link"] for d in report["gates"]["links"]["dangling"]], ["../deploy/missing.py"])
        self.assertEqual([c["cited"] for c in report["gates"]["links"]["cited_paths_not_exported"]],
                         ["scripts/not_exported.py"])

    def test_absolute_local_paths_fail(self):
        write(self.root, "deploy/run.json", json.dumps({"root": LOCAL}))
        code, report = self.export(self.manifest())
        self.assertEqual(code, 1)
        self.assertFalse(report["gates"]["absolute_local_paths"]["passed"])
        self.assertEqual(report["gates"]["absolute_local_paths"]["files"], ["deploy/run.json"])

    def test_redacted_placeholders_pass_the_path_gate(self):
        write(self.root, "deploy/run.json", json.dumps({"root": "<repo>/scripts/x.json", "key": "<local>/…/k.txt"}))
        code, report = self.export(self.manifest())
        self.assertEqual(code, 0)
        self.assertTrue(report["gates"]["absolute_local_paths"]["passed"])

    def test_unmatched_required_entry_fails_and_optional_is_a_notice(self):
        code, report = self.export(self.manifest("verify | scripts/absent.py | needed", "verify | ?scripts/maybe.py | later"))
        self.assertEqual(code, 1)
        self.assertEqual(report["manifest"]["unmatched_required"], [{"line": 4, "glob": "scripts/absent.py"}])
        self.assertEqual(report["manifest"]["unmatched_optional"], [{"line": 5, "glob": "scripts/maybe.py"}])

    def test_exclusion_entry_removes_earlier_matches(self):
        write(self.root, "deploy/scratch.py", "x = 1\n")
        code, report = self.export(self.manifest("deploy | !deploy/scratch.py | not public"))
        self.assertEqual(code, 0)
        self.assertFalse((self.out / "deploy/scratch.py").exists())
        self.assertTrue((self.out / "deploy/serve.py").exists())


if __name__ == "__main__":
    unittest.main()
