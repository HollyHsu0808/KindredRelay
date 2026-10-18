"""Run deterministic family-site checks sequentially and preserve one final result.

No dependency installation, credentials, model downloads or training. Each test's
own exit status is authoritative. Unittest checks must also execute >0 cases.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def source_identity() -> dict[str, str]:
    paths = list((ROOT / "handoff_day1/agent").glob("*.py"))
    paths += list((ROOT / "handoff_day1/ui").rglob("*.py"))
    paths += list((ROOT / "handoff_day1/scripts").glob("*.py"))
    paths += [ROOT / "scripts/eval_handoff_replay.py"]
    paths += [p for p in (ROOT / "handoff_day1/care_cases").rglob("*") if p.is_file()]
    paths += [ROOT / "handoff_day1/integration_samples/primock57/day1_consultation01_seg087_doctor.wav"]
    paths += list((ROOT / "deploy").glob("*.py"))
    paths += list((ROOT / "deploy").glob("*requirements*"))
    paths += [ROOT / "Dockerfile.release", ROOT / "requirements.txt", ROOT / "handoff_day1/RELEASE_VERSION.txt"]
    return {str(p.relative_to(ROOT)).replace("\\", "/"): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(set(paths))}


def display_path(path: Path) -> str:
    """Repository-relative when inside the repository, else absolute (an --out outside it)."""
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def run(output: Path) -> int:
    output.mkdir(parents=True, exist_ok=False)
    before = source_identity()
    commands = [([sys.executable, "agent/" + p.name], ROOT / "handoff_day1", p.stem != "test_guardrails")
                for p in sorted((ROOT / "handoff_day1/agent").glob("test_*.py"))]
    commands += [([sys.executable, "ui/" + name], ROOT / "handoff_day1", True)
                 for name in ("test_timeline_page.py", "test_timeline_storage.py", "test_plan_provider_failure.py", "test_app_shell.py",
                              "test_timeline_storage_residue.py", "test_toast_headline.py")]
    commands += [([sys.executable, "deploy/" + p.name], ROOT, True)
                 for p in sorted((ROOT / "deploy").glob("test_*.py"))]
    replay = ROOT / "scripts/eval_handoff_replay.py"
    if not replay.is_file():
        raise FileNotFoundError("HandoffReplay entry point is required for the A+B+D suite")
    commands.append(([sys.executable, "scripts/eval_handoff_replay.py", "--out", str(output / "replay")], ROOT, False))
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1",
           "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"}
    # Checks inject explicit doubles where needed; never inherit an enabled live
    # verifier or a real service endpoint from the caller's shell.
    for name in tuple(env):
        if name.startswith(("CARERELAY_LLM_", "CARERELAY_PHOTO_", "KINDRED_VERIFIER_")):
            env.pop(name)
    env["KINDRED_VERIFIER_MODE"] = "off"
    # Saved timelines go under --out, never the caller's store or the page's default ~/.kindredrelay.
    env["CARERELAY_STATE_DIR"] = str(output / "state")
    results = []
    for index, (command, cwd, unittest_check) in enumerate(commands, 1):
        name = Path(command[1]).stem
        started = time.monotonic()
        print(f"[{index}/{len(commands)}] {command[1]}", flush=True)
        try:
            completed = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True,
                                       encoding="utf-8", errors="replace", timeout=300)
            stdout, stderr, code = completed.stdout, completed.stderr, completed.returncode
        except subprocess.TimeoutExpired as exc:
            def decode(value):
                return value.decode("utf-8", "replace") if isinstance(value, bytes) else (value or "")
            stdout, stderr, code = decode(exc.stdout), decode(exc.stderr) + "\nRunner timeout (300 seconds).", None
        out_file, err_file = output / f"{index:02d}_{name}.stdout.log", output / f"{index:02d}_{name}.stderr.log"
        out_file.write_text(stdout, encoding="utf-8")
        err_file.write_text(stderr, encoding="utf-8")
        counts = re.findall(r"\bRan (\d+) tests? in\b", stdout + "\n" + stderr)
        count = int(counts[-1]) if counts else None
        passed = code == 0 and (not unittest_check or (count is not None and count > 0))
        results.append({"command": command, "cwd": str(cwd), "exit_code": code,
                        "unittest_cases": count, "requires_unittest_count": unittest_check,
                        "passed": passed, "seconds": round(time.monotonic() - started, 3),
                        "stdout": display_path(out_file), "stderr": display_path(err_file)})
        print(f"  exit={code}; unittest_cases={count}; passed={passed}", flush=True)
    versions = {}
    for name in ("streamlit", "pandas", "numpy", "requests", "tzdata", "torch", "transformers", "sentencepiece", "protobuf"):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    after = source_identity()
    unchanged = before == after
    passed = unchanged and all(r["passed"] for r in results)
    report = {"completed_utc": dt.datetime.now(dt.timezone.utc).isoformat(), "python": sys.version,
              "executable": sys.executable, "packages": versions, "root": str(ROOT),
              "scope": "Deterministic engine/UI tests. Doubles do not validate trained-model accuracy or deployment.",
              "source_sha256": before, "sources_unchanged_during_run": unchanged,
              "test_processes": len(results), "unittest_cases": sum(r["unittest_cases"] or 0 for r in results),
              "results": results, "passed": passed, "exit_code": 0 if passed else 1}
    (output / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"RESULT: {'PASS' if passed else 'FAIL'}; unittest_cases={report['unittest_cases']}; sources_unchanged={unchanged}", flush=True)
    return report["exit_code"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "release/validation_abd/final")
    options = parser.parse_args()
    raise SystemExit(run(options.out.resolve()))
