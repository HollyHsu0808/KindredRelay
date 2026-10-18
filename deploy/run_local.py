"""Local full-feature launcher; --demo is the explicit partial-mode alternative.

--check performs local readiness checks only, without downloads or API calls.
--configure prompts for endpoint/model metadata and a masked API key, then saves
root-level TOML strings in the ignored .streamlit/secrets.toml. Existing process
environment values take precedence over that file, including --secrets-file.
Streamlit receives an empty secrets-file override so its automatic project/user
secret loading cannot overwrite the validated child environment at bootstrap.
Configured model IDs are not evidence that the endpoint currently offers them.
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import tomllib
from urllib.parse import urlsplit
import warnings

from serve import validate_verifier_config

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = ("CARERELAY_LLM_BASE_URL", "CARERELAY_LLM_MODEL", "CARERELAY_PHOTO_MODEL", "CARERELAY_LLM_API_KEY")
ALLOWED = set(REQUIRED) | {"CARERELAY_LLM_BACKEND", "CARERELAY_LLM_GUIDED_JSON", "CARERELAY_LLM_TIMEOUT_S",
    "CARERELAY_ASR_MODEL", "KINDRED_VERIFIER_MODE", "KINDRED_VERIFIER_DIR", "KINDRED_VERIFIER_THREADS", "PORT"}
DEFAULTS = {"CARERELAY_LLM_BASE_URL": "https://developer.amd.com.cn/radeon/api/v1",
            "CARERELAY_LLM_MODEL": "DeepSeek-V4-Flash", "CARERELAY_PHOTO_MODEL": "MiniCPM-V-4.7-1B"}


def read_settings(path: Path) -> dict:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        raise ValueError("Secrets file could not be read or parsed as TOML") from None
    if any(not isinstance(value, str) for key, value in data.items() if key in ALLOWED):
        raise ValueError("Whitelisted secret settings must be root-level TOML strings")
    return data


def validate_endpoint(value: str) -> None:
    try:
        url = urlsplit(value)
        allowed = url.scheme == "https" or (url.scheme == "http" and url.hostname in ("localhost", "127.0.0.1", "::1"))
        valid = allowed and url.hostname and url.username is None and url.password is None and url.port != 0
        valid = valid and "?" not in value and "#" not in value and not any(c.isspace() or ord(c) < 32 for c in value)
    except ValueError:
        valid = False
    if not valid:
        raise ValueError("Endpoint must use HTTPS, or HTTP on localhost, without inline credentials, query or fragment")


def user_path() -> str:
    """Read the existing Windows user PATH; never install or change the registry."""
    if os.name != "nt":
        return ""
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            value, _ = winreg.QueryValueEx(key, "Path")
        return value if isinstance(value, str) else ""
    except OSError:
        return ""


def child_environment(base: dict, settings: dict) -> dict:
    env = {**{key: value for key, value in settings.items() if key in ALLOWED}, **base}
    original = env.get("PATH", "")
    extra = [os.path.expandvars(part.strip('"')) for part in user_path().split(os.pathsep) if part]
    extra = [part for part in extra if Path(part).is_dir() and part not in original.split(os.pathsep)]
    env["PATH"] = os.pathsep.join(([original] if original else []) + extra)
    env.setdefault("KINDRED_VERIFIER_MODE", "off")
    env.setdefault("CARERELAY_ASR_MODEL", "base.en")
    env.setdefault("CARERELAY_LLM_GUIDED_JSON", "0")
    return env


def asr_missing(env: dict) -> list[str]:
    sys.path.insert(0, str(ROOT / "handoff_day1/agent"))
    from asr_local import missing
    absent = [name for name in missing() if name != "ffmpeg"]
    if shutil.which("ffmpeg", path=env.get("PATH", "")) is None:
        absent.append("ffmpeg")
    return absent


def readiness(env: dict, demo: bool = False) -> dict:
    present = {key: bool(env.get(key, "").strip()) for key in REQUIRED}
    errors = []
    if present["CARERELAY_LLM_BASE_URL"]:
        try:
            validate_endpoint(env["CARERELAY_LLM_BASE_URL"])
        except ValueError:
            errors.append("invalid_endpoint")
    try:
        validate_verifier_config(env)
    except ValueError:
        errors.append("invalid_verifier_configuration")
    absent = asr_missing(env)
    if not demo:
        if absent: errors.append("speech_dependencies_missing")
        if not all(present.values()): errors.append("live_settings_missing")
        if env.get("CARERELAY_LLM_BACKEND", "openai") != "openai": errors.append("live_backend_must_be_openai")
    return {"mode": "demo_partial" if demo else "full", "ready": not errors,
            "settings_present": present, "speech_dependencies_present": not absent,
            "speech_missing": absent, "live_endpoint_tested": False, "errors": errors}


def command(isolated_secrets: Path) -> list[str]:
    return [sys.executable, "-m", "streamlit", "run", str(ROOT / "handoff_day1/ui/pages/1_Family_timeline.py"),
            "--server.address", "127.0.0.1", "--server.port", "8501", "--server.headless", "true",
            "--browser.gatherUsageStats", "false", "--server.maxUploadSize", "25",
            "--secrets.files", str(isolated_secrets)]


def configure(path: Path, base: dict) -> None:
    destination, project = path.resolve(), ROOT.resolve()
    if destination.is_relative_to(project) and not destination.is_relative_to(project / ".streamlit"):
        raise ValueError("Configuration inside the project must stay in the ignored .streamlit directory")
    old = read_settings(path)
    if set(old) - ALLOWED:
        raise ValueError("Existing secret file has other settings; use a separate --secrets-file")
    chosen = dict(old)
    print("Model defaults are suggestions from the release configuration, not live-validated availability.")
    for key, label in ((REQUIRED[0], "Endpoint"), (REQUIRED[1], "Text model"), (REQUIRED[2], "Vision model")):
        default = old.get(key) or DEFAULTS[key]
        # A stored endpoint may itself be invalid. Do not echo its contents.
        prompt_default = DEFAULTS[key]
        value = input(f"{label} (blank keeps existing setting, otherwise default {prompt_default}): ").strip()
        chosen[key] = value or default
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        try:
            chosen[REQUIRED[3]] = getpass.getpass("API key (hidden; blank keeps existing key): ") or old.get(REQUIRED[3], "")
        except getpass.GetPassWarning:
            raise ValueError("A terminal with masked input is required") from None
    if any(not chosen.get(key, "").strip() for key in REQUIRED):
        raise ValueError("All four live settings are required before saving")
    if any(any(ord(c) < 32 or ord(c) == 127 for c in value) for value in chosen.values()):
        raise ValueError("Secret settings must contain single-line text")
    validate_endpoint(chosen[REQUIRED[0]])
    # Validate the file itself and the effective environment before replacing it.
    validate_verifier_config(chosen)
    effective = {**chosen, **base}
    validate_endpoint(effective[REQUIRED[0]])
    if effective.get("CARERELAY_LLM_BACKEND", "openai") != "openai":
        raise ValueError("Full mode requires CARERELAY_LLM_BACKEND=openai")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".local-settings-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as file:
            file.write("".join(f"{key} = {json.dumps(value, ensure_ascii=False)}\n" for key, value in sorted(chosen.items())))
            file.flush(); os.fsync(file.fileno())
        os.replace(temporary, path)
    finally:
        if Path(temporary).exists(): Path(temporary).unlink()
    print("Local secret settings saved. Existing process environment takes precedence.")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--check", action="store_true")
    action.add_argument("--configure", action="store_true")
    parser.add_argument("--demo", action="store_true", help="Explicit partial mode; live features may be unavailable")
    parser.add_argument("--secrets-file", type=Path, default=ROOT / ".streamlit/secrets.toml")
    args = parser.parse_args(argv)
    try:
        if args.configure:
            configure(args.secrets_file, dict(os.environ))
            return 0
        env = child_environment(dict(os.environ), read_settings(args.secrets_file))
        report = readiness(env, args.demo)
        print(json.dumps(report), flush=True)
        if not report["ready"]: return 2
        if args.check: return 0
        # Streamlit's supported multiple-value CLI option replaces its search
        # list. An empty tuple restores defaults, so provide one real empty
        # TOML file instead. Keep it alive until the child has exited.
        with tempfile.TemporaryDirectory(prefix="kindredrelay-runtime-") as folder:
            isolated = Path(folder) / "empty.toml"
            isolated.write_text("", encoding="utf-8")
            return subprocess.call(command(isolated), cwd=ROOT, env=env)
    except (OSError, ValueError, EOFError, KeyboardInterrupt):
        # Neither parser snippets, paths nor configured values enter error output.
        print("Local startup/configuration failed. Check TOML, endpoint, backend and optional verifier settings.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
