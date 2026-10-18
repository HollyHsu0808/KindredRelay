"""Deployment configuration regression checks; no network or model calls."""
import unittest
import json
import tempfile
from pathlib import Path
from serve import command


class TestReleaseCommand(unittest.TestCase):
    def test_live_release_requires_all_credentials_without_echoing_values(self):
        with self.assertRaisesRegex(ValueError, "CARERELAY_LLM_API_KEY"):
            command({"CARERELAY_LLM_BASE_URL": "https://example.test/v1", "CARERELAY_LLM_MODEL": "text",
                     "CARERELAY_PHOTO_MODEL": "vision"})

    def test_command_uses_family_page_and_platform_port(self):
        args = command({"CARERELAY_REQUIRE_LIVE": "0", "PORT": "10000"})
        root = Path(__file__).resolve().parents[1]
        entry = Path(args[args.index("run") + 1])
        self.assertEqual(entry.relative_to(root).as_posix(), "handoff_day1/ui/pages/shell/kindred_app.py")
        self.assertTrue(entry.is_file())
        # Dockerfile.release copies only ui/pages/ of the UI: the entry and the family page it opens by default are in it
        self.assertIn("COPY handoff_day1/ui/pages/ /app/handoff_day1/ui/pages/", (root / "Dockerfile.release").read_text(encoding="utf-8"))
        shell = entry.read_text(encoding="utf-8")
        self.assertIn('FAMILY_PAGE = HERE.parent / "1_Family_timeline.py"', shell)
        self.assertIn('st.Page(FAMILY_PAGE, title="Family timeline", icon="👪", default=True)', shell)
        self.assertTrue((entry.parent.parent / "1_Family_timeline.py").is_file())
        self.assertEqual(args[args.index("--server.port") + 1], "10000")
        self.assertEqual(args[args.index("--server.address") + 1], "0.0.0.0")

    def test_invalid_port_is_rejected(self):
        for port in ("0", "65536", "abc", "8501;something"):
            with self.subTest(port=port), self.assertRaises(ValueError):
                command({"PORT": port})

    def test_verifier_off_needs_no_bundle(self):
        self.assertTrue(command({"CARERELAY_REQUIRE_LIVE": "0", "KINDRED_VERIFIER_MODE": "off"}))

    def test_verifier_rejects_invalid_configuration(self):
        base = {"CARERELAY_REQUIRE_LIVE": "0"}
        for settings, message in (({"KINDRED_VERIFIER_MODE": "unknown"}, "MODE"),
                                  ({"KINDRED_VERIFIER_MODE": "shadow"}, "DIR"),
                                  ({"KINDRED_VERIFIER_MODE": "shadow", "KINDRED_VERIFIER_THREADS": "0"}, "THREADS")):
            with self.subTest(settings=settings), self.assertRaisesRegex(ValueError, message):
                command({**base, **settings})

    def test_gate_needs_full_and_useful_operating_point(self):
        with tempfile.TemporaryDirectory() as folder:
            env = {"CARERELAY_REQUIRE_LIVE": "0", "KINDRED_VERIFIER_MODE": "gate", "KINDRED_VERIFIER_DIR": folder}
            for stage, useful in (("smoke", True), ("full", False), ("full", "true")):
                Path(folder, "verifier.json").write_text(json.dumps({"stage": stage, "validation_operating_point_found": useful}), encoding="utf-8")
                with self.subTest(stage=stage, useful=useful), self.assertRaisesRegex(ValueError, "Gate requires"):
                    command(env)
            Path(folder, "verifier.json").write_text(json.dumps({"stage": "full", "validation_operating_point_found": True}), encoding="utf-8")
            self.assertTrue(command(env))  # Config check only: no model weights are loaded here.

    def test_invalid_manifest_is_rejected_without_echoing_its_contents(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder, "verifier.json")
            for contents in ("private-invalid-data", "[]"):
                path.write_text(contents, encoding="utf-8")
                with self.subTest(contents=contents), self.assertRaises(ValueError) as caught:
                    command({"CARERELAY_REQUIRE_LIVE": "0", "KINDRED_VERIFIER_MODE": "shadow", "KINDRED_VERIFIER_DIR": folder})
                self.assertNotIn(contents, str(caught.exception))


if __name__ == "__main__":
    unittest.main()
