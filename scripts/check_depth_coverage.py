#!/usr/bin/env python3
"""Check that the public documents cover every engineering-depth item, and that what they cite next to it exists.
No network, model, key or third-party package: the standard library only.

python scripts/check_depth_coverage.py [--root DIR] [--files F ...] [--ids D01-D19] [--strict] [--json OUT]

Default documents (relative to --root): README.md and EVIDENCE.md when present at the root (the public repository's
front page and evidence index), and, always required, submission/slides.md, submission/SUBMISSION_TEXT.md and
submission/JUDGES_QUICKSTART.md. --files replaces that list (each file is then required).

Checks, per document:
  coverage   every id (default D01 to D19) appears, as a marker `<!-- depth:D05 -->` (several ids may share one
             marker: `<!-- depth:D05 D06 -->`) or written out as the bare id (`D05`). A missing id is a failure.
  links      in each paragraph that holds a marker (the lines between two blank lines), every relative Markdown
             link `[text](target)` or `href="target"` must resolve from the document's folder (a leading / from
             --root), and every backticked repository path (`scripts/x.py`, `release/benchmarks/run/`, with an
             optional :line suffix; its first part must exist at --root) must exist; a glob (*) must match. A
             broken one is a failure.
  evidence   every evidence folder named anywhere in the document (release/benchmarks/<run>, research/<study>)
             must exist; a glob must match one; placeholders such as <UTC> are not checked. A missing one is a
             failure.
  pending    every [[...]] placeholder is listed with its line: a warning, a failure with --strict.

Exit 0 when nothing fails, 1 otherwise, 2 on a usage error. The last line is `RESULT: PASS` or `RESULT: FAIL ...`.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "kindredrelay-depth-coverage-v1"
OPTIONAL = ("README.md", "EVIDENCE.md")
REQUIRED = ("submission/slides.md", "submission/SUBMISSION_TEXT.md", "submission/JUDGES_QUICKSTART.md")
MARKER = re.compile(r"<!--\s*depth:\s*([^>]*?)\s*-->")
ID_IN_MARKER = re.compile(r"\bD\d{2}\b")
MD_LINK = re.compile(r"(?<!!)\[[^\]\n]*\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)|!\[[^\]\n]*\]\(\s*<?([^)\s>]+)>?")
HREF = re.compile(r"""\b(?:href|src)\s*=\s*["']([^"']+)["']""")
TICK = re.compile(r"`([^`\n]+)`")
REPO_PATH = re.compile(r"^(?:\./)?[A-Za-z0-9_.\-]+(?:/[A-Za-z0-9_.\-*]+)+/?(?::\d[\d,\-]*)?$")
EVIDENCE = re.compile(r"(?<![\w/.\-])((?:release/benchmarks|research)/[^\s`'\"()\[\]|,;]+)")
PLACEHOLDER = re.compile(r"\[\[[^\]\n]*\]\]")
SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*:")


def parse_ids(spec: str) -> list[str]:
    """'D01-D19' or 'D01,D03,D07' (or both mixed) -> ['D01', ...]; a bad spec raises ValueError."""
    out: list[str] = []
    for part in [p.strip() for p in spec.split(",") if p.strip()]:
        m = re.fullmatch(r"D(\d{2})(?:\s*-\s*D(\d{2}))?", part)
        if not m:
            raise ValueError(f"not an id or a range of ids: {part!r}")
        a, b = int(m.group(1)), int(m.group(2) or m.group(1))
        if b < a:
            raise ValueError(f"empty range: {part!r}")
        out += [f"D{n:02d}" for n in range(a, b + 1) if f"D{n:02d}" not in out]
    if not out:
        raise ValueError("no ids")
    return out


def paragraphs(lines: list[str]) -> list[tuple[int, int]]:
    """(first, last) 0-based line indexes of each run of non-blank lines."""
    out, start = [], None
    for i, line in enumerate(lines):
        if line.strip():
            start = i if start is None else start
        elif start is not None:
            out.append((start, i - 1))
            start = None
    if start is not None:
        out.append((start, len(lines) - 1))
    return out


def glob_exists(root: Path, rel: str) -> bool:
    rel = rel.strip("/")
    if "*" in rel:
        return any(root.glob(rel))
    return (root / rel).exists()


def placeholder_like(text: str) -> bool:
    return any(c in text for c in "<>{}[]") or "..." in text or "…" in text


def link_targets(text: str) -> list[str]:
    out = [m.group(1) or m.group(2) for m in MD_LINK.finditer(text)]
    return [t for t in out + HREF.findall(text) if t]


def check_link(target: str, doc: Path, root: Path) -> str | None:
    """None when the relative link resolves (or is not relative); else the problem."""
    t = target.strip()
    if not t or t.startswith("#") or SCHEME.match(t) or t.startswith("//") or placeholder_like(t):
        return None
    t = re.split(r"[#?]", t, 1)[0]
    if not t:
        return None
    base = root if t.startswith("/") else doc.parent
    path = (base / t.lstrip("/")).resolve()
    if "*" in t:
        ok = any(Path(path.anchor).glob(str(path.relative_to(path.anchor)).replace("\\", "/")))
    else:
        ok = path.exists()
    return None if ok else f"link ({target}) does not resolve"


def check_tick_path(token: str, root: Path) -> str | None:
    """None when a backticked repository path exists (or the token is not one); else the problem."""
    tok = token.strip()
    if not REPO_PATH.match(tok) or placeholder_like(tok):
        return None
    tok = tok[2:] if tok.startswith("./") else tok
    path = re.sub(r":\d[\d,\-]*$", "", tok)
    first = path.split("/", 1)[0]
    if not (root / first).exists():   # not a repository path (a host name, a key path, a model id ...)
        return None
    return None if glob_exists(root, path) else f"path `{token}` does not exist"


def evidence_dirs(text: str) -> list[str]:
    """The evidence folders a text names: release/benchmarks/<run> or research/<study> (first part after it)."""
    out = []
    for m in EVIDENCE.finditer(text):
        parts = m.group(1).rstrip(".:").split("/")
        n = 3 if parts[0] == "release" else 2
        if len(parts) < n or not parts[n - 1]:
            continue
        name = "/".join(parts[:n])
        if placeholder_like(name) or name.endswith("_") or name.endswith("-"):
            continue
        if name not in out:
            out.append(name)
    return out


def check_doc(path: Path, root: Path, ids: list[str]) -> dict:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    marked: dict[str, list[int]] = {}
    marker_lines: list[int] = []
    for i, line in enumerate(lines):
        for m in MARKER.finditer(line):
            marker_lines.append(i)
            for d in ID_IN_MARKER.findall(m.group(1)):
                marked.setdefault(d, []).append(i + 1)
    no_markers = MARKER.sub(" ", text)
    coverage = {}
    for d in ids:
        if d in marked:
            coverage[d] = "marker"
        elif re.search(rf"(?<![\w\-]){d}(?![\w\-])", no_markers):
            coverage[d] = "id"
        else:
            coverage[d] = "missing"
    link_problems, seen = [], set()
    for first, last in paragraphs(lines):
        if not any(first <= i <= last for i in marker_lines):
            continue
        for n in range(first, last + 1):
            line = lines[n]
            found = [check_link(t, path, root) for t in link_targets(line)]
            found += [check_tick_path(t, root) for t in TICK.findall(MARKER.sub(" ", line))]
            for p in found:
                if p and (n, p) not in seen:
                    seen.add((n, p))
                    link_problems.append({"line": n + 1, "problem": p})
    evidence = []
    for name in evidence_dirs(text):
        if not glob_exists(root, name):
            where = next(i + 1 for i, line in enumerate(lines) if name in line)
            evidence.append({"line": where, "problem": f"evidence folder {name} does not exist"})
    pending = [{"line": i + 1, "text": m.group(0)[:160]} for i, line in enumerate(lines) for m in PLACEHOLDER.finditer(line)]
    return {"coverage": coverage, "markers": {d: marked[d] for d in sorted(marked)}, "links": link_problems,
            "evidence": evidence, "pending": pending}


def default_files(root: Path) -> list[tuple[str, bool]]:
    return [(f, False) for f in OPTIONAL if (root / f).is_file()] + [(f, True) for f in REQUIRED]


def run(root: Path, files: list[str] | None, ids: list[str], strict: bool) -> dict:
    targets = [(f, True) for f in files] if files else default_files(root)
    docs, failures = {}, []
    for name, _required in targets:
        p = Path(name) if Path(name).is_absolute() else root / name
        key = p.relative_to(root).as_posix() if p.is_relative_to(root) else str(p)
        if not p.is_file():
            docs[key] = {"error": "file not found"}
            failures.append(f"{key}: required document not found")
            continue
        r = docs[key] = check_doc(p, root, ids)
        failures += [f"{key}: {d} not covered" for d, how in r["coverage"].items() if how == "missing"]
        failures += [f"{key}:{x['line']}: {x['problem']}" for x in r["links"] + r["evidence"]]
        if strict:
            failures += [f"{key}:{x['line']}: placeholder {x['text']}" for x in r["pending"]]
    return {"schema_version": SCHEMA, "root": str(root), "ids": ids, "strict": strict, "documents": docs,
            "failures": failures, "result": "FAIL" if failures else "PASS"}


def table(report: dict) -> list[str]:
    docs = [k for k, v in report["documents"].items() if "coverage" in v]
    short = {"marker": "M", "id": "I", "missing": "-"}
    width = max([len(k) for k in docs] + [8])
    out = ["coverage (M = marker, I = id written out, - = missing):",
           "  " + "document".ljust(width) + " " + " ".join(report["ids"])]
    for k in docs:
        cov = report["documents"][k]["coverage"]
        out.append("  " + k.ljust(width) + " " + " ".join(short[cov[d]].center(3) for d in report["ids"]))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", type=Path, default=ROOT, help="repository root (default: this checkout)")
    ap.add_argument("--files", nargs="+", default=None, help="documents to check, relative to --root (all required)")
    ap.add_argument("--ids", default="D01-D19", help="ids to require, e.g. D01-D19 or D01,D04 (default D01-D19)")
    ap.add_argument("--strict", action="store_true", help="also fail on [[...]] placeholders")
    ap.add_argument("--json", type=Path, default=None, help="write the JSON report here (parent must exist)")
    args = ap.parse_args(argv)
    root = args.root.resolve()
    if not root.is_dir():
        print(f"error: --root {root} is not a directory", file=sys.stderr)
        return 2
    try:
        ids = parse_ids(args.ids)
    except ValueError as exc:
        print(f"error: --ids: {exc}", file=sys.stderr)
        return 2
    report = run(root, args.files, ids, args.strict)
    if args.json:
        args.json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    enc = getattr(sys.stdout, "encoding", None) or "ascii"
    lines = table(report)
    for k, v in report["documents"].items():
        for x in v.get("pending", []):
            lines.append(f"{'PENDING' if not args.strict else 'FAIL   '} {k}:{x['line']}: {x['text']}")
    lines += [f"FAIL    {f}" for f in report["failures"] if "placeholder [[" not in f]
    n_pending = sum(len(v.get("pending", [])) for v in report["documents"].values())
    lines.append(f"documents={len(report['documents'])}, ids={len(ids)}, placeholders={n_pending}"
                 + (" (warnings; --strict fails on them)" if not args.strict else ""))
    lines.append(f"RESULT: {report['result']}" + (f"; failing checks={len(report['failures'])}" if report["failures"] else ""))
    for line in lines:
        print(line.encode(enc, "replace").decode(enc, "replace"))
    return 1 if report["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
