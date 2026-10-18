"""Local launcher security/readiness regressions; fake settings, no network or models."""
from __future__ import annotations

import contextlib
import getpass
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
import sys
from unittest.mock import patch

import run_local as local

FAKE_KEY = "fixture-only-never-a-real-credential"
FULL = {"CARERELAY_LLM_BASE_URL": "https://endpoint.example/v1", "CARERELAY_LLM_MODEL": "fixture-text",
        "CARERELAY_PHOTO_MODEL": "fixture-vision", "CARERELAY_LLM_API_KEY": FAKE_KEY}


class LocalLauncherTests(unittest.TestCase):
    def test_full_requires_each_live_setting_and_speech_dependencies(self):
        with patch.object(local, "asr_missing", return_value=[]):
            self.assertTrue(local.readiness(FULL)["ready"])
            for key in local.REQUIRED:
                with self.subTest(key=key):
                    env = {k: v for k, v in FULL.items() if k != key}
                    report = local.readiness(env)
                    self.assertFalse(report["ready"])
                    self.assertFalse(report["settings_present"][key])
            self.assertNotIn(FAKE_KEY, json.dumps(local.readiness(FULL)))
        with patch.object(local, "asr_missing", return_value=["ffmpeg"]):
            self.assertIn("speech_dependencies_missing", local.readiness(FULL)["errors"])

    def test_disabled_or_inprocess_backend_cannot_pass_full_readiness(self):
        with patch.object(local, "asr_missing", return_value=[]):
            for backend in ("none", "transformers:fixture-model", "unknown"):
                report = local.readiness({**FULL, "CARERELAY_LLM_BACKEND": backend})
                self.assertFalse(report["ready"])
                self.assertIn("live_backend_must_be_openai", report["errors"])

    def test_endpoint_rejects_remote_http_credentials_queries_and_fragments(self):
        for value in ("http://remote.example/v1", "https://user:fixture-private@endpoint.example/v1",
                      "https://endpoint.example/v1?key=fixture-private", "https://endpoint.example/#fixture-private",
                      "https://endpoint.example:bad/v1", "https://endpoint.example/\nfixture-private", "not-a-url"):
            with self.subTest(value=value), self.assertRaises(ValueError) as caught:
                local.validate_endpoint(value)
            self.assertNotIn("fixture-private", str(caught.exception))
            self.assertNotIn(value, str(caught.exception))
        for value in ("https://endpoint.example/v1", "http://localhost:8000/v1", "http://127.0.0.1/v1", "http://[::1]:8000/v1"):
            local.validate_endpoint(value)

    def test_fixed_command_has_no_public_bind_or_key_argument(self):
        command = local.command(Path("synthetic-empty.toml"))
        self.assertEqual(command[command.index("--server.address") + 1], "127.0.0.1")
        self.assertEqual(command[command.index("--server.port") + 1], "8501")
        self.assertNotIn("0.0.0.0", command)
        self.assertNotIn(FAKE_KEY, " ".join(command))
        self.assertEqual(command[command.index("--secrets.files") + 1], "synthetic-empty.toml")

    def test_only_explicit_demo_bypasses_missing_features(self):
        with patch.object(local, "asr_missing", return_value=["openai-whisper", "ffmpeg"]):
            self.assertFalse(local.readiness({})["ready"])
            report = local.readiness({}, demo=True)
            self.assertTrue(report["ready"])
            self.assertEqual(report["mode"], "demo_partial")
            self.assertFalse(report["live_endpoint_tested"])

    def test_check_does_not_create_files_or_start_child_and_redacts_values(self):
        with tempfile.TemporaryDirectory() as folder:
            output, errors = io.StringIO(), io.StringIO()
            with patch.object(local, "ROOT", Path(folder)), patch.dict(os.environ, FULL, clear=True), \
                 patch.object(local, "asr_missing", return_value=[]), patch.object(local, "user_path", return_value=""), \
                 patch.object(local.subprocess, "call") as start, contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
                self.assertEqual(local.main(["--check"]), 0)
            self.assertEqual(list(Path(folder).iterdir()), [])
            self.assertFalse(start.called)
            self.assertNotIn(FAKE_KEY, output.getvalue() + errors.getvalue())
            self.assertNotIn(folder, output.getvalue() + errors.getvalue())
            self.assertFalse(json.loads(output.getvalue())["live_endpoint_tested"])

    def test_default_missing_full_settings_prevents_start(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(local, "ROOT", Path(folder)), \
             patch.dict(os.environ, {}, clear=True), patch.object(local, "asr_missing", return_value=[]), \
             patch.object(local, "user_path", return_value=""), patch.object(local.subprocess, "call") as start, \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(local.main([]), 2)
            start.assert_not_called()
            self.assertEqual(local.main(["--demo"]), start.return_value)
            start.assert_called_once()

    def test_file_settings_whitelist_and_environment_precedence(self):
        with patch.object(local, "user_path", return_value=""):
            merged = local.child_environment({"CARERELAY_LLM_API_KEY": "environment-fixture", "PATH": "existing-path"},
                                             {**FULL, "UNRELATED_SECRET": "must-not-pass"})
        self.assertEqual(merged["CARERELAY_LLM_API_KEY"], "environment-fixture")
        self.assertEqual(merged["CARERELAY_PHOTO_MODEL"], FULL["CARERELAY_PHOTO_MODEL"])
        self.assertNotIn("UNRELATED_SECRET", merged)
        self.assertEqual(merged["PATH"], "existing-path")
        self.assertEqual(merged["KINDRED_VERIFIER_MODE"], "off")

    def test_user_path_adds_existing_directories_without_mutating_original_environment(self):
        with tempfile.TemporaryDirectory() as folder:
            existing, fresh = Path(folder) / "existing", Path(folder) / "ffmpeg-bin"
            existing.mkdir(); fresh.mkdir()
            base = {"PATH": str(existing)}
            registry = os.pathsep.join((str(existing), str(fresh), str(Path(folder) / "missing")))
            with patch.object(local, "user_path", return_value=registry):
                env = local.child_environment(base, {})
            self.assertEqual(base, {"PATH": str(existing)})
            self.assertEqual(env["PATH"].split(os.pathsep), [str(existing), str(fresh)])

    def test_invalid_toml_and_nonstring_whitelisted_settings_never_echo_contents(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "secret.toml"
            for contents in ('CARERELAY_LLM_API_KEY = "fixture-private', 'CARERELAY_LLM_API_KEY = 123'):
                path.write_text(contents, encoding="utf-8")
                with self.assertRaises(ValueError) as caught: local.read_settings(path)
                self.assertNotIn("fixture-private", str(caught.exception))

    def test_explicit_secrets_file_is_loaded_without_echoing_key_or_path(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "fixture-settings.toml"
            path.write_text("".join(f"{key} = {json.dumps(value)}\n" for key, value in FULL.items()), encoding="utf-8")
            output, errors = io.StringIO(), io.StringIO()
            with patch.dict(os.environ, {}, clear=True), patch.object(local, "asr_missing", return_value=[]), \
                 patch.object(local, "user_path", return_value=""), contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
                self.assertEqual(local.main(["--check", "--secrets-file", str(path)]), 0)
            self.assertNotIn(FAKE_KEY, output.getvalue() + errors.getvalue())
            self.assertNotIn(str(path), output.getvalue() + errors.getvalue())
            path.write_text('CARERELAY_LLM_API_KEY = "fixture-private', encoding="utf-8")
            output, errors = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
                self.assertEqual(local.main(["--check", "--secrets-file", str(path)]), 2)
            self.assertNotIn("fixture-private", output.getvalue() + errors.getvalue())
            self.assertNotIn(str(path), output.getvalue() + errors.getvalue())

    def test_configure_masks_key_and_atomically_saves_root_strings(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / ".streamlit" / "secrets.toml"
            output = io.StringIO()
            with patch("builtins.input", side_effect=["", "", ""]), \
                 patch.object(local.getpass, "getpass", return_value=FAKE_KEY) as secret_prompt, contextlib.redirect_stdout(output):
                local.configure(path, {})
            settings = local.read_settings(path)
            self.assertEqual(settings["CARERELAY_LLM_API_KEY"], FAKE_KEY)
            self.assertTrue(all(isinstance(value, str) for value in settings.values()))
            secret_prompt.assert_called_once()
            self.assertNotIn(FAKE_KEY, output.getvalue())
            self.assertEqual(list(path.parent.iterdir()), [path])

    def test_configure_failure_preserves_existing_file_and_unknown_settings(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.toml"
            path.write_text('UNRELATED = "preserve-me"\n', encoding="utf-8")
            before = path.read_bytes()
            with self.assertRaises(ValueError), patch("builtins.input") as prompt:
                local.configure(path, {})
            prompt.assert_not_called()
            self.assertEqual(path.read_bytes(), before)
            path.write_text("".join(f"{key} = {json.dumps(value)}\n" for key, value in FULL.items()), encoding="utf-8")
            before = path.read_bytes()
            with patch("builtins.input", side_effect=["https://endpoint.example?key=fixture-private", "", ""]), \
                 patch.object(local.getpass, "getpass", return_value=FAKE_KEY), contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(ValueError): local.configure(path, {})
            self.assertEqual(path.read_bytes(), before)

    def test_configure_never_writes_project_secrets_outside_ignored_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "project"; root.mkdir()
            rejected = root / "local-settings.toml"
            with patch.object(local, "ROOT", root), patch("builtins.input") as prompt:
                with self.assertRaises(ValueError): local.configure(rejected, {})
            self.assertFalse(rejected.exists())
            prompt.assert_not_called()
            for target in (root / ".streamlit/custom.toml", Path(folder) / "outside-project.toml"):
                with patch.object(local, "ROOT", root), patch("builtins.input", side_effect=["", "", ""]), \
                     patch.object(local.getpass, "getpass", return_value=FAKE_KEY), contextlib.redirect_stdout(io.StringIO()):
                    local.configure(target, {})
                self.assertEqual(local.read_settings(target)["CARERELAY_LLM_API_KEY"], FAKE_KEY)
    def test_atomic_replace_failure_preserves_file_and_removes_temporary(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.toml"
            path.write_text("".join(f"{key} = {json.dumps(value)}\n" for key, value in FULL.items()), encoding="utf-8")
            before = path.read_bytes()
            with patch("builtins.input", side_effect=["", "", ""]), patch.object(local.getpass, "getpass", return_value=FAKE_KEY), \
                 patch.object(local.os, "replace", side_effect=OSError("fixture-private")), contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(OSError): local.configure(path, {})
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(list(path.parent.iterdir()), [path])

    def test_getpass_fallback_cannot_echo_key_or_write_configuration(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.toml"
            with patch("builtins.input", side_effect=["", "", ""]), \
                 patch.object(local.getpass, "getpass", side_effect=getpass.GetPassWarning("fixture-warning")), \
                 contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(ValueError): local.configure(path, {})
            self.assertFalse(path.exists())

    def test_started_child_receives_settings_as_environment_not_arguments(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(local, "ROOT", Path(folder)), \
             patch.dict(os.environ, FULL, clear=True), patch.object(local, "asr_missing", return_value=[]), \
             patch.object(local, "user_path", return_value=""), patch.object(local.subprocess, "call", return_value=0) as start, \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(local.main([]), 0)
            args, kwargs = start.call_args
            self.assertNotIn(FAKE_KEY, " ".join(args[0]))
            self.assertEqual(kwargs["env"]["CARERELAY_LLM_API_KEY"], FAKE_KEY)
            self.assertEqual(kwargs["cwd"], Path(folder))

    def test_real_streamlit_cli_bootstrap_cannot_override_validated_env(self):
        """Exercise installed Click parsing and bootstrap, without starting a server."""
        code = r'''
import json, os, sys
from pathlib import Path
from unittest.mock import patch
from click.testing import CliRunner
from streamlit import config
from streamlit.web import bootstrap, cli
data = json.load(sys.stdin)
def checked_bootstrap(file, args=None, flag_options=None):
    config._main_script_path = str(Path(file).resolve())
    bootstrap.load_config_options(flag_options or {})
    bootstrap.prepare_streamlit_environment(file)
    for name, expected in data["expected"].items():
        if os.environ.get(name) != expected:
            raise AssertionError("validated child environment was overwritten: " + name)
    if list(config.get_option("secrets.files")) != [data["isolated_file"]]:
        raise AssertionError("default secret search paths were not isolated")
    if Path(data["isolated_file"]).read_bytes() != b"":
        raise AssertionError("runtime isolation file must be empty")
with patch.object(cli, "_main_run", side_effect=checked_bootstrap):
    result = CliRunner().invoke(cli.main, data["args"])
if result.exit_code != 0:
    print("synthetic bootstrap isolation failed: " + type(result.exception).__name__)
    sys.exit(1)
print("synthetic CLI/bootstrap isolation passed")
'''
        with tempfile.TemporaryDirectory() as folder:
            root, home = Path(folder) / "project", Path(folder) / "home"
            root.mkdir(); home.mkdir()
            app = root / "handoff_day1/ui/pages/1_Family_timeline.py"
            app.parent.mkdir(parents=True); app.write_text("# synthetic target; never executed\n")
            for directory in (root, home):
                (directory / ".streamlit").mkdir()
                (directory / ".streamlit/secrets.toml").write_text(
                    'CARERELAY_LLM_BASE_URL = "http://untrusted.example/v1"\n'
                    'CARERELAY_LLM_MODEL = "default-file-must-not-override"\n'
                    'CARERELAY_LLM_API_KEY = "synthetic-default-key"\n', encoding="utf-8")
            custom = root / "chosen.toml"
            custom.write_text("".join(f"{key} = {json.dumps(value)}\n" for key, value in FULL.items()), encoding="utf-8")
            base = {key: os.environ[key] for key in ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP") if key in os.environ}
            base.update(USERPROFILE=str(home), HOME=str(home), CARERELAY_LLM_API_KEY="synthetic-env-wins",
                        CARERELAY_LLM_MODEL="environment-model-wins")
            runtime_files = []
            def probe(command, *, cwd, env):
                isolated = command[command.index("--secrets.files") + 1] if "--secrets.files" in command else None
                if isolated is not None: runtime_files.append(Path(isolated))
                expected = {**FULL, "CARERELAY_LLM_API_KEY": "synthetic-env-wins", "CARERELAY_LLM_MODEL": "environment-model-wins"}
                result = local.subprocess.run([sys.executable, "-c", code], cwd=cwd, env=env,
                    input=json.dumps({"args": command[3:], "expected": expected, "isolated_file": isolated}),
                    capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                return result.returncode
            with patch.object(local, "ROOT", root), patch.dict(os.environ, base, clear=True), \
                 patch.object(local, "asr_missing", return_value=[]), patch.object(local, "user_path", return_value=""), \
                 patch.object(local.subprocess, "call", side_effect=probe), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(local.main(["--secrets-file", str(custom)]), 0)
            self.assertEqual(len(runtime_files), 1)
            self.assertFalse(runtime_files[0].exists())


if __name__ == "__main__":
    unittest.main()
