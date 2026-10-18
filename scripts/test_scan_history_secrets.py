"""Offline tests of scripts/scan_history_secrets.py on a throwaway git repository (needs git; no network, no
repository data). Every secret-shaped string is assembled at run time, so this file itself matches no pattern.

.venv/Scripts/python.exe scripts/test_scan_history_secrets.py
"""
from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import io
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import scan_history_secrets as S  # noqa: E402

FAKE_SK = "sk" + "-" + "Q7" * 14                    # openai_style_sk shape, built here
FAKE_KEY = "kr" + "9Zt" * 12                          # an 'exact key' that matches no pattern on its own


def git(repo: Path, *a):
    subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True)


@unittest.skipUnless(shutil.which("git"), "git not on PATH")
class ScanHistory(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        git(self.repo, "init", "-q")
        git(self.repo, "config", "user.email", "t@example.invalid")
        git(self.repo, "config", "user.name", "t")
        git(self.repo, "config", "commit.gpgsign", "false")

    def commit(self, files: dict[str, str]):
        for name, text in files.items():
            p = self.repo / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "c")

    def run_scan(self, *extra) -> tuple[int, str]:
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = S.main([str(self.repo), *extra])
        return code, buf.getvalue()

    def test_a_clean_history_has_no_hits(self):
        self.commit({"a.txt": "nothing to see\n"})
        code, out = self.run_scan()
        self.assertEqual(code, 0)
        self.assertIn("pattern hits: none", out)
        self.assertIn("exact-key check: off", out)

    def test_a_key_in_an_old_commit_is_found_and_its_value_never_printed(self):
        self.commit({"cfg.py": f"client = make({FAKE_SK!r})\n"})
        self.commit({"cfg.py": "client = make(None)\n"})          # removed later: still in history
        code, out = self.run_scan()
        self.assertEqual(code, 0)   # hits are reported, not an exit status
        self.assertIn("HIT openai_style_sk\tcfg.py\tblobs=", out)
        self.assertNotIn(FAKE_SK, out)
        self.assertNotIn(FAKE_SK[:12], out)

    def test_a_name_at_a_line_end_does_not_pair_with_the_next_line(self):
        # 'token:' then a long identifier on the next line: \s* used to cross the newline (a false positive)
        self.commit({"notes.md": "token:\n" + "abcdefghij" * 3 + "\n", "conf.ini": "secret = " + "k9" * 15 + "\n"})
        code, out = self.run_scan()
        self.assertNotIn("notes.md", out)
        self.assertIn("HIT assigned_api_key\tconf.ini", out)     # the same line still counts
        self.assertEqual(code, 0)   # hits are reported, not an exit status

    def test_the_exact_key_check_reads_the_key_file_and_prints_neither_key_nor_path(self):
        key_file = self.root / "private" / "the_key_file.txt"
        key_file.parent.mkdir()
        key_file.write_text(FAKE_KEY + "\n", encoding="utf-8")
        self.commit({"log.txt": f"request with {FAKE_KEY} sent\n", "b.txt": "fine\n"})
        code, out = self.run_scan(str(key_file))
        self.assertEqual(code, 0)   # hits are reported, not an exit status
        self.assertIn("exact-key check: on", out)
        self.assertIn("HIT EXACT_TOKEN_FACTORY_KEY\tlog.txt", out)
        self.assertNotIn("b.txt", out)
        self.assertNotIn(FAKE_KEY, out)
        self.assertNotIn("the_key_file", out)
        self.assertNotIn(str(key_file.parent), out)

    def test_suspicious_names_are_listed_and_trees_are_not_counted_as_blobs(self):
        self.commit({"dir/.env": "A=1\n", "dir/b.txt": "x\n"})
        code, out = self.run_scan()
        self.assertEqual(code, 0)
        self.assertIn("suspicious file names: ['dir/.env']", out)
        self.assertIn("blobs scanned: 2;", out)

    def test_usage_error(self):
        with redirect_stderr(io.StringIO()):
            self.assertEqual(S.main([]), 2)
            self.assertEqual(S.main(["--exact-key-file"]), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
