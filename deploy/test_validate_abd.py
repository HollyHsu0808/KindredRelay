"""validate_abd runner bookkeeping; every check process is a stub, so no suite runs here."""
from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import validate_abd


def stub_process(command, **kwargs):
    return subprocess.CompletedProcess(command, 0, stdout="Ran 1 test in 0.001s\n\nOK\n", stderr="")


class ValidateAbdOutputPathTests(unittest.TestCase):
    def test_log_paths_are_repository_relative_inside_and_absolute_outside(self):
        inside = validate_abd.ROOT / "release/validation_abd/fixture/01_test_x.stdout.log"
        self.assertEqual(validate_abd.display_path(inside), str(Path("release/validation_abd/fixture/01_test_x.stdout.log")))
        with tempfile.TemporaryDirectory() as folder:
            outside = Path(folder).resolve() / "01_test_x.stdout.log"
            self.assertFalse(outside.is_relative_to(validate_abd.ROOT))
            self.assertEqual(validate_abd.display_path(outside), str(outside))

    def test_out_outside_repository_completes_and_records_absolute_log_paths(self):
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder).resolve() / "validation"
            calls = []

            def record(command, **kwargs):
                calls.append(command)
                return stub_process(command, **kwargs)

            with patch.object(validate_abd, "source_identity", return_value={}), \
                    patch.object(validate_abd.subprocess, "run", side_effect=record), \
                    contextlib.redirect_stdout(io.StringIO()) as printed:
                self.assertEqual(validate_abd.run(out), 0)
            self.assertIn("RESULT: PASS", printed.getvalue())
            report = json.loads((out / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(len(report["results"]), len(calls))
            self.assertGreater(len(calls), 1)
            for result in report["results"]:
                for stream in ("stdout", "stderr"):
                    path = Path(result[stream])
                    self.assertTrue(path.is_absolute())
                    self.assertEqual(path.parent, out)
                    self.assertTrue(path.is_file())


class ValidateAbdChecksTests(unittest.TestCase):
    def run_stubbed(self, folder):
        out, calls = Path(folder).resolve() / "validation", []

        def record(command, **kwargs):
            calls.append((command, kwargs))
            return stub_process(command, **kwargs)

        with patch.object(validate_abd, "source_identity", return_value={}), \
                patch.object(validate_abd.subprocess, "run", side_effect=record), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(validate_abd.run(out), 0)
        return out, calls, json.loads((out / "summary.json").read_text(encoding="utf-8"))

    def test_checks_save_timelines_under_out_never_in_the_callers_state_dir(self):
        with tempfile.TemporaryDirectory() as folder:
            caller = str(Path(folder) / "callers_real_store")
            with patch.dict(validate_abd.os.environ, {"CARERELAY_STATE_DIR": caller}):
                out, calls, _ = self.run_stubbed(folder)
        self.assertGreater(len(calls), 1)
        for command, kwargs in calls:
            state = Path(kwargs["env"]["CARERELAY_STATE_DIR"])
            self.assertNotEqual(str(state), caller)
            self.assertTrue(state.is_relative_to(out) and state != out, (command, state))

    def test_ui_timeline_storage_shell_and_plan_failure_suites_are_run(self):
        with tempfile.TemporaryDirectory() as folder:
            _, calls, report = self.run_stubbed(folder)
        ran = {(Path(kwargs["cwd"]) / command[1]).resolve() for command, kwargs in calls}
        counted = {(Path(r["cwd"]) / r["command"][1]).resolve() for r in report["results"] if r["requires_unittest_count"]}
        for name in ("test_timeline_page.py", "test_timeline_storage.py", "test_app_shell.py", "test_plan_provider_failure.py"):
            path = (validate_abd.ROOT / "handoff_day1/ui" / name).resolve()
            self.assertIn(path, ran)
            self.assertIn(path, counted, "a UI suite must execute more than zero unittest cases")


if __name__ == "__main__":
    unittest.main()
