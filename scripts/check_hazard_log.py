#!/usr/bin/env python3
"""Check that every citation in submission/HAZARD_LOG.md still points at what it says. Offline, standard library only.

python scripts/check_hazard_log.py [--log submission/HAZARD_LOG.md] [--out REPORT.json]

For every hazard row (first cell HZ-NN) of the log's table:
  - `path:line` (or `path:a-b`) must name an existing file and line; a ("quote") written right after it must be on that
    line (or range), so a citation that drifted after an edit is caught;
  - `file.py::test_name` must name an existing test file that defines `def test_name(`; the file must be run by
    deploy/validate_abd.py (its own selection rule, read from that file) or be listed in the log's section
    "Tests not run by deploy/validate_abd.py";
  - `path.json` -> `key` = value must resolve in that JSON file and equal the value (key syntax of
    scripts/verify_claims.py, plus [field=value] to pick a list element, e.g. per_category[category=fabricated_quote]);
  - severity and likelihood are integers 1..5, the score columns equal their product, the status starts with open,
    mitigated or accepted, and each row cites at least one control and one piece of verification evidence.
Exit 0 when every check passes, 1 otherwise, 2 on a usage error.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import verify_claims as V  # noqa: E402  key resolution and value comparison shared with the claims check

ROOT = Path(__file__).resolve().parents[1]
STATUSES = ("open", "mitigated", "accepted")
LINE = re.compile(r"^(?P<path>[^`:\s][^`:]*\.[A-Za-z0-9]+):(?P<lines>\d+(?:-\d+)?)$")
TEST = re.compile(r"^(?P<path>[^`:\s]+\.py)::(?P<name>test_\w+)$")
NOT_COVERED_HEADING = "Tests not run by deploy/validate_abd.py"


def validated_test_files(root: Path) -> set[str]:
    """The test files deploy/validate_abd.py runs, from its own selection rule: test_*.py globs in run() and the
    named handoff_day1/ui tests."""
    src = (root / "deploy/validate_abd.py").read_text(encoding="utf-8")
    body = src.split("def run(", 1)[1] if "def run(" in src else src
    out = set()
    for d in re.findall(r'\(ROOT / "([^"]+)"\)\.glob\("test_\*\.py"\)', body):
        out |= {f"{d}/{p.name}" for p in (root / d).glob("test_*.py")}
    for names in re.findall(r"for name in \(([^)]*)\)", body):
        out |= {f"handoff_day1/ui/{n}" for n in re.findall(r'"([^"]+\.py)"', names)}
    return out


def section_files(text: str, heading: str) -> set[str]:
    """Backticked .py paths listed under a '## heading' (up to the next heading)."""
    m = re.search(r"^##+\s*" + re.escape(heading) + r"[^\n]*\n(.*?)(?=^##|\Z)", text, re.S | re.M)
    return set(re.findall(r"`([^`]+\.py)`", m.group(1))) if m else set()


def resolve(obj, path: str) -> list:
    """V.resolve plus [field=value] list selection."""
    m = re.search(r"\[(\w+)=([^\]]+)\]", path)
    if not m:
        return V.resolve(obj, path)
    out = []
    for lst in (V.resolve(obj, path[:m.start()]) if path[:m.start()] else [obj]):
        if isinstance(lst, list):
            for item in lst:
                if isinstance(item, dict) and str(item.get(m.group(1))) == m.group(2):
                    out += resolve(item, path[m.end():])
    if not out:
        raise KeyError(path)
    return out


def rows(text: str):
    for i, line in enumerate(text.splitlines(), 1):
        if line.startswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if cells and re.fullmatch(r"HZ-\d{2}", cells[0]):
                yield i, cells


def check(root: Path, log: Path) -> dict:
    text = log.read_text(encoding="utf-8")
    header = next((ln for ln in text.splitlines() if ln.startswith("| ID ")), "")
    cols = [c.strip().lower() for c in header.strip().strip("|").split("|")]
    need = ("severity", "likelihood", "score", "controls", "verification", "residual", "status")

    def col(name: str) -> int:
        return next(i for i, c in enumerate(cols) if c.startswith(name))

    checks, problems = [], []
    if not all(any(c.startswith(n) for c in cols) for n in need):
        problems.append(f"table header lacks one of {need}: {cols}")
        return {"checks": checks, "problems": problems, "result": "FAIL"}
    validated = validated_test_files(root)
    listed = section_files(text, NOT_COVERED_HEADING)
    seen_ids = set()
    for lineno, cells in rows(text):
        hid, where = cells[0], f"HAZARD_LOG.md:{lineno}"
        if hid in seen_ids:
            problems.append(f"{where} {hid}: duplicate id")
        seen_ids.add(hid)
        if len(cells) != len(cols):
            problems.append(f"{where} {hid}: {len(cells)} cells, header has {len(cols)}")
            continue
        nums = {}
        for name in ("severity", "likelihood"):
            v = cells[col(name)]
            if not re.fullmatch(r"[1-5]", v):
                problems.append(f"{where} {hid}: {name} {v!r} is not 1..5")
            nums[name] = int(v) if v.isdigit() else None
        score = cells[col("score")]
        if nums["severity"] and nums["likelihood"] and score != str(nums["severity"] * nums["likelihood"]):
            problems.append(f"{where} {hid}: score {score!r} != severity x likelihood")
        rm = re.match(r"S([1-5])\s*[x×]\s*L([1-5])\s*=\s*(\d+)", cells[col("residual")])
        if not rm or int(rm.group(1)) * int(rm.group(2)) != int(rm.group(3)):
            problems.append(f"{where} {hid}: residual must start 'S<n> x L<n> = <product>'")
        if not cells[col("status")].lower().startswith(STATUSES):
            problems.append(f"{where} {hid}: status must start with one of {STATUSES}")
        for kind in ("controls", "verification"):
            cell = cells[col(kind)]
            n_cites = 0
            for seg in V.split_outside_backticks(cell, ";"):
                for tok in re.findall(r"`([^`]+)`", seg):
                    tok = tok.strip()
                    if (lm := LINE.match(tok)) and not tok.endswith(".json"):
                        n_cites += 1
                        checks.append(line_check(root, hid, tok, lm, seg, problems, where))
                    elif tm := TEST.match(tok):
                        n_cites += 1
                        checks.append(test_check(root, hid, tm, validated, listed, problems, where))
                jm = re.search(r"`([^`]+\.json)`\s*→\s*`([^`]+)`\s*=\s*([^;]+)", seg)
                if jm:
                    n_cites += 1
                    checks.append(json_check(root, hid, jm, problems, where))
            if n_cites == 0:
                problems.append(f"{where} {hid}: no checkable citation in {kind}")
    if not seen_ids:
        problems.append("no hazard rows (first cell HZ-NN) found")
    return {"checks": checks, "problems": problems, "hazards": sorted(seen_ids),
            "validated_test_files": sorted(validated), "listed_not_covered": sorted(listed),
            "result": "FAIL" if problems else "PASS"}


def line_check(root, hid, tok, lm, seg, problems, where) -> dict:
    f = root / lm.group("path")
    row = {"hazard": hid, "cite": tok, "ok": False}
    if not f.is_file():
        problems.append(f"{where} {hid}: {tok}: file not found")
        return row
    lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
    a, _, b = lm.group("lines").partition("-")
    lo, hi = int(a), int(b or a)
    if hi > len(lines) or lo < 1 or hi < lo:
        problems.append(f"{where} {hid}: {tok}: the file has {len(lines)} lines")
        return row
    after = seg.split(f"`{tok}`", 1)[1]
    qm = re.match(r'\s*\(\s*"(.+?)"\s*\)', after)
    if qm:
        cited = V.squash(" ".join(lines[lo - 1:hi]))
        row["quote"] = qm.group(1)
        if V.squash(qm.group(1)) not in cited:
            found = [i for i, ln in enumerate(lines, 1) if V.squash(qm.group(1)) in V.squash(ln)]
            problems.append(f"{where} {hid}: {tok}: quote not on the cited line(s)"
                            + (f" (found at line {found[0]})" if found else " (not in the file)"))
            return row
    row["ok"] = True
    return row


def test_check(root, hid, tm, validated, listed, problems, where) -> dict:
    path, name = tm.group("path"), tm.group("name")
    row = {"hazard": hid, "cite": f"{path}::{name}", "ok": False, "run_by_validate_abd": path in validated}
    f = root / path
    if not f.is_file():
        problems.append(f"{where} {hid}: {path}: test file not found")
        return row
    if not re.search(rf"^\s*def {re.escape(name)}\(", f.read_text(encoding="utf-8", errors="replace"), re.M):
        problems.append(f"{where} {hid}: {path} has no test {name}")
        return row
    if path not in validated and path not in listed:
        problems.append(f"{where} {hid}: {path} is neither run by deploy/validate_abd.py nor listed under "
                        f"'{NOT_COVERED_HEADING}'")
        return row
    row["ok"] = True
    return row


def json_check(root, hid, jm, problems, where) -> dict:
    path, key, value = jm.group(1), jm.group(2), jm.group(3).strip()
    row = {"hazard": hid, "cite": f"{path} -> {key} = {value}", "ok": False}
    f = root / path
    if not f.is_file():
        problems.append(f"{where} {hid}: {path}: file not found")
        return row
    try:
        vals = resolve(json.loads(f.read_text(encoding="utf-8")), key)
    except (KeyError, json.JSONDecodeError) as exc:
        problems.append(f"{where} {hid}: {path} -> {key}: not found ({exc})")
        return row
    claim = V.parse_value(value)
    for v in vals:
        ok, why = V.value_matches(dict(claim) if isinstance(claim, dict) else claim, v)
        if not ok:
            problems.append(f"{where} {hid}: {path} -> {key} = {value}: {why}")
            return row
    row["ok"] = True
    return row


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", type=Path, default=ROOT, help="repository root (default: this checkout)")
    ap.add_argument("--log", type=Path, default=None, help="hazard log (default: submission/HAZARD_LOG.md)")
    ap.add_argument("--out", type=Path, default=None, help="write the JSON report here")
    args = ap.parse_args(argv)
    root = args.root.resolve()
    log = args.log or root / "submission/HAZARD_LOG.md"
    if not log.is_file() or not (root / "deploy/validate_abd.py").is_file():
        print(f"error: need {log} and {root / 'deploy/validate_abd.py'}", file=sys.stderr)
        return 2
    rep = check(root, log)
    if args.out:
        args.out.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    enc = getattr(sys.stdout, "encoding", None) or "ascii"
    for p in rep["problems"]:
        print(("PROBLEM " + p).encode(enc, "replace").decode(enc, "replace"))
    n_tests = sum(1 for c in rep["checks"] if "run_by_validate_abd" in c)
    n_run = sum(1 for c in rep["checks"] if c.get("run_by_validate_abd"))
    print(f"hazards={len(rep.get('hazards', []))}; citations checked={len(rep['checks'])}; "
          f"tests cited={n_tests} (run by validate_abd: {n_run})")
    print(f"RESULT: {rep['result']}" + (f"; problems={len(rep['problems'])}" if rep["problems"] else ""))
    return 0 if rep["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
