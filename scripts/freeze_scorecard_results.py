#!/usr/bin/env python3
"""Freeze the run results the Evaluation & Safety Scorecard reads into handoff_day1/ui/pages/shell/data/. Dockerfile.release
copies ui/pages/ into the image but not release/, so without these copies the deployed page has no run results.

Copies only each run's result file, never its records or logs:
  --tf-bench DIR (repeatable)  DIR/results.json of scripts/bench_tf_handover.py  -> data/tf_bench_<name>.json
  --redteam DIR                DIR/results.json of scripts/redteam_safety.py     -> data/redteam.json
  --redteam-before DIR         optional: an earlier red-team run, kept in redteam.json for before/after
  --validation DIR             DIR/summary.json of deploy/validate_abd.py        -> data/validation.json
  --crosscheck DIR             optional: DIR/results.json of scripts/crosscheck_judge.py eval -> data/crosscheck.json
<name> is DIR's folder name without its tf_bench_ prefix. --tf-label TEXT (repeatable, in --tf-bench order) names a
benchmark run on the page (e.g. "Main run", "Qwen, thinking off"); without one the page names it by its models and
extra request body. Each file is {"frozen": {source_dir, source_file, source_sha256 (of the file as copied), ...},
"doc": the result as it was} with two changes: in every argv / command list, the path given to --api-key-file, and any
entry that names a key or secrets file, reads "<redacted path>"; and every absolute local path under the user profile
reads <repo>/... or <local>/.../<name> (scripts/redact_local_paths.py; frozen.local_paths_redacted counts them, numbers
are checked unchanged; source_sha256 stays the digest of the source file). validation.json also lists the test files of this
checkout that the run did not execute (from its own commands) and names a git commit only when the summary records one.
The data folder then holds exactly these snapshots: earlier tf_bench_*.json, redteam.json, validation.json and
crosscheck.json go (a freeze without --crosscheck removes crosscheck.json).

  .venv/Scripts/python.exe scripts/freeze_scorecard_results.py --tf-bench release/benchmarks/tf_bench_A \\
      --tf-bench release/benchmarks/tf_bench_B --tf-label "Main run" --tf-label "Qwen, thinking off" \\
      --redteam release/benchmarks/redteam_C --validation release/validation_abd/D

Exit 0 when written, 2 when an input is missing or not the expected result file (nothing is written then). Stdlib
only; no network.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
SHELL = ROOT / "handoff_day1" / "ui" / "pages" / "shell"
DATA = SHELL / "data"
sys.path.insert(0, str(SHELL))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import scorecard_data as D  # noqa: E402
import redact_local_paths as R  # noqa: E402

SCHEMA = "kindredrelay-scorecard-snapshot-v1"
REDACTED = "<redacted path>"
KEY_FLAGS = ("--api-key-file",)
KEY_LIKE = re.compile(r"(?i)api[_-]?key|secret|credential|private|token|password|\.pem$|\.key$|\.env$")
ARGV_KEYS = ("argv", "command")
MANAGED = (D.FROZEN_TF_BENCH, D.FROZEN_REDTEAM, D.FROZEN_VALIDATION, D.FROZEN_CROSSCHECK)
EXIT_OK, EXIT_USAGE = 0, 2


class FreezeError(Exception):
    """An input that cannot be frozen; nothing was written."""


def redact_argv(argv: list) -> tuple[list, list[str]]:
    """argv with the --api-key-file value, and any path-like entry naming a key or secrets file, as <redacted path>.
    Returns (clean argv, the values removed)."""
    out, removed, hide = [], [], False
    for a in argv:
        if not isinstance(a, str):
            out.append(a)
            hide = False
            continue
        flag, eq, value = a.partition("=")
        if hide:
            out.append(REDACTED)
            if a != REDACTED:
                removed.append(a)
        elif eq and flag in KEY_FLAGS:
            out.append(f"{flag}={REDACTED}")
            if value != REDACTED:
                removed.append(value)
        elif ("/" in a or "\\" in a) and KEY_LIKE.search(a):
            out.append(REDACTED)
            removed.append(a)
        else:
            out.append(a)
        hide = a in KEY_FLAGS
    return out, removed


def scrub(obj, removed: list[str]):
    """A copy of obj with every argv / command list redacted (redact_argv); removed collects what was taken out."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k in ARGV_KEYS and isinstance(v, list):
                v, gone = redact_argv(v)
                removed += gone
            out[k] = scrub(v, removed)
        return out
    if isinstance(obj, list):
        return [scrub(v, removed) for v in obj]
    return obj


def display(path: Path) -> str:
    p = Path(path).resolve()
    try:
        return p.relative_to(ROOT).as_posix()
    except ValueError:
        return p.as_posix()


def load(folder: Path, name: str, kind: str) -> tuple[dict, dict]:
    """(meta, doc) of folder/name: the parsed JSON object, its sha256 and where it came from."""
    path = Path(folder) / name
    try:
        raw = path.read_bytes()
        doc = json.loads(raw.decode("utf-8"))
    except OSError as e:
        raise FreezeError(f"{kind}: cannot read {path} ({type(e).__name__})") from None
    except ValueError:
        raise FreezeError(f"{kind}: {path} is not JSON") from None
    if not isinstance(doc, dict):
        raise FreezeError(f"{kind}: {path} does not hold a JSON object")
    meta = {"schema": SCHEMA, "kind": kind, "source_dir": display(folder), "source_file": name,
            "source_sha256": hashlib.sha256(raw).hexdigest(), "frozen_by": "scripts/freeze_scorecard_results.py"}
    return meta, doc


def check_tf_bench(doc: dict, where: str) -> None:
    import bench_tf_handover as B   # imported here: it loads the agent modules
    errs = B.validate_results(doc)
    if errs:
        raise FreezeError(f"tf_bench: {where} is not a valid benchmark results.json: {'; '.join(errs[:5])}")


def check_redteam(doc: dict, where: str) -> None:
    if not (isinstance(doc.get("summary"), dict) and isinstance(doc.get("run"), dict) and isinstance(doc.get("cases"), list)):
        raise FreezeError(f"redteam: {where} is not a red-team results.json (summary, run, cases)")


def check_crosscheck(doc: dict, where: str) -> None:
    if not (str(doc.get("schema_version") or "").startswith("kindredrelay-crosscheck-v1")
            and isinstance(doc.get("acceptance"), dict) and isinstance(doc.get("sets"), dict)
            and isinstance(doc.get("dry_run"), bool)):
        raise FreezeError(f"crosscheck: {where} is not a scripts/crosscheck_judge.py results.json (schema_version, "
                          "dry_run, acceptance, sets)")


def check_validation(doc: dict, where: str) -> None:
    if not (isinstance(doc.get("results"), list) and isinstance(doc.get("passed"), bool)):
        raise FreezeError(f"validation: {where} is not a deploy/validate_abd.py summary.json (results, passed)")


def snapshot_name(folder: Path) -> str:
    name = re.sub(r"[^A-Za-z0-9._-]", "_", Path(folder).resolve().name)
    name = name[len("tf_bench_"):] if name.startswith("tf_bench_") else name
    if not name:
        raise FreezeError(f"tf_bench: {folder} gives an empty snapshot name")
    if "token" in name.lower():   # .gitignore ignores *token*: the snapshot would never be committed
        raise FreezeError(f"tf_bench: snapshot name tf_bench_{name}.json contains 'token', which .gitignore ignores; "
                          "rename the folder")
    return f"tf_bench_{name}.json"


def build(tf_bench: list[Path], tf_labels: list[str], redteam: Path, validation: Path,
          redteam_before: Path | None = None, now: str | None = None, crosscheck: Path | None = None) -> dict[str, dict]:
    """{file name: snapshot} for the data folder; FreezeError before anything is written."""
    if len(tf_labels) > len(tf_bench):
        raise FreezeError("more --tf-label than --tf-bench")
    now = now or dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    out: dict[str, dict] = {}
    for i, folder in enumerate(tf_bench):
        meta, doc = load(folder, "results.json", "tf_bench")
        check_tf_bench(doc, f"{folder}/results.json")
        records = Path(folder) / "records.jsonl"
        if records.is_file() and records.stat().st_mtime > (Path(folder) / "results.json").stat().st_mtime:
            raise FreezeError(f"tf_bench: {records} is newer than its results.json (still running, or resumed): "
                              "freeze it when the run has written results.json")
        name = snapshot_name(folder)
        if name in out:
            raise FreezeError(f"tf_bench: two folders give {name}; freeze runs with distinct folder names")
        meta["label"] = tf_labels[i] if i < len(tf_labels) else None
        out[name] = {"frozen": meta, "doc": doc}
    meta, doc = load(redteam, "results.json", "redteam")
    check_redteam(doc, f"{redteam}/results.json")
    out[D.FROZEN_REDTEAM] = {"frozen": meta, "doc": doc}
    if redteam_before is not None:
        meta_b, doc_b = load(redteam_before, "results.json", "redteam_before")
        check_redteam(doc_b, f"{redteam_before}/results.json")
        out[D.FROZEN_REDTEAM]["before"] = {"frozen": meta_b, "doc": doc_b}
    meta, doc = load(validation, "summary.json", "validation")
    check_validation(doc, f"{validation}/summary.json")
    head = D.get(doc, "git", "head") or doc.get("git_head")
    ran = D.tests_run_by(doc)
    meta.update(git_head=head if isinstance(head, str) and re.fullmatch(r"[0-9a-f]{7,40}", head) else None,
                tests_run=sorted(ran) if ran is not None else None,
                not_covered=D.tests_not_run(doc, ROOT),
                not_covered_inventory="test_*.py under " + ", ".join(D.TEST_ROOTS) + " (git ls-files -co --exclude-standard) "
                                      "at freeze time, minus the run's results[].command")
    out[D.FROZEN_VALIDATION] = {"frozen": meta, "doc": doc}
    if crosscheck is not None:
        meta_c, doc_c = load(crosscheck, "results.json", "crosscheck")
        check_crosscheck(doc_c, f"{crosscheck}/results.json")
        records = Path(crosscheck) / "records.jsonl"
        if records.is_file() and records.stat().st_mtime > (Path(crosscheck) / "results.json").stat().st_mtime:
            raise FreezeError(f"crosscheck: {records} is newer than its results.json (still running, or resumed): "
                              "freeze it when eval has written results.json")
        out[D.FROZEN_CROSSCHECK] = {"frozen": meta_c, "doc": doc_c}
    for snap in out.values():   # redact, then make sure nothing that was taken out is still anywhere in the file
        for part in [snap] + ([snap["before"]] if "before" in snap else []):
            removed: list[str] = []
            part["doc"] = scrub(part["doc"], removed)
            local = [0]
            doc = R.Redactor().obj(part["doc"], local)
            if R.values_sha256([doc]) != R.values_sha256([part["doc"]]):
                raise FreezeError(f"{part['frozen']['kind']}: redacting local paths changed a non-string value; not frozen")
            part["doc"] = doc
            part["frozen"].update(frozen_utc=now, redacted_entries=len(removed), local_paths_redacted=local[0],
                                  local_path_rule="scripts/redact_local_paths.py: " + R.RULE)
            text = json.dumps(part["doc"], ensure_ascii=False)
            for gone in removed:
                if gone and (gone in text or json.dumps(gone, ensure_ascii=False)[1:-1] in text):
                    raise FreezeError(f"{part['frozen']['kind']}: a redacted key-file path still appears elsewhere in "
                                      f"{part['frozen']['source_dir']}/{part['frozen']['source_file']}; not frozen")
    return out


def write(snapshots: dict[str, dict], data: Path = DATA) -> tuple[list[Path], list[Path]]:
    """Replace the managed snapshots in data with these. Returns (written, removed)."""
    data = Path(data)
    data.mkdir(parents=True, exist_ok=True)
    stale = sorted({p for pat in MANAGED for p in data.glob(pat)} - {data / n for n in snapshots})
    written = []
    for name, snap in snapshots.items():
        path = data / name
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(snap, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp.replace(path)
        written.append(path)
    for p in stale:
        p.unlink()
    return written, stale


def main(argv: list[str] | None = None, data: Path = DATA) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tf-bench", type=Path, action="append", required=True, metavar="DIR",
                    help="a scripts/bench_tf_handover.py output folder (repeatable)")
    ap.add_argument("--tf-label", action="append", default=[], metavar="TEXT", help="name of the run, in --tf-bench order")
    ap.add_argument("--redteam", type=Path, required=True, metavar="DIR", help="a scripts/redteam_safety.py output folder")
    ap.add_argument("--redteam-before", type=Path, default=None, metavar="DIR", help="an earlier red-team run (optional)")
    ap.add_argument("--validation", type=Path, required=True, metavar="DIR", help="a deploy/validate_abd.py --out folder")
    ap.add_argument("--crosscheck", type=Path, default=None, metavar="DIR",
                    help="a scripts/crosscheck_judge.py output folder with results.json (optional)")
    args = ap.parse_args(argv)
    try:
        snaps = build(args.tf_bench, args.tf_label, args.redteam, args.validation, args.redteam_before,
                      crosscheck=args.crosscheck)
    except FreezeError as e:
        print(f"freeze_scorecard_results: {e}", file=sys.stderr)
        return EXIT_USAGE
    written, removed = write(snaps, data)
    for p in written:
        meta = snaps[p.name]["frozen"]
        print(f"wrote {display(p)} <- {meta['source_dir']}/{meta['source_file']} (sha256 {meta['source_sha256'][:12]}, "
              f"{meta['redacted_entries']} argv entries and {meta['local_paths_redacted']} local paths redacted)")
    for p in removed:
        print(f"removed {display(p)} (not in this freeze)")
    v = snaps[D.FROZEN_VALIDATION]
    if not D.suite_passed(v["doc"]):
        print(f"warning: {v['frozen']['source_dir']} is RESULT FAIL; the scorecard shows it as FAIL", file=sys.stderr)
    if v["frozen"]["git_head"] is None:
        print("note: the validation summary records no git commit; the scorecard names the run folder instead")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
