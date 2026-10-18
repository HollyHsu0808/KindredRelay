#!/usr/bin/env python3
"""Stage the public KindredRelay repository from this checkout and gate it. Offline, standard library only.

python scripts/export_public_repo.py --out DIR [--exact-key-file PATH] [--root REPO] [--public PUBLIC_DIR]

Copies the files that public_repo/MANIFEST.txt allows (nothing else), writes README.md, DEPLOY.md, EVIDENCE.md and
LICENSE from public_repo/ at the export root, then checks the staged tree and writes DIR/EXPORT_REPORT.json:
  (i)   CJK characters (U+3000-U+9FFF, U+F900-U+FAFF, U+FF00-U+FFEF) in any text file not listed in
        public_repo/CJK_ALLOWLIST.txt                                                     -> failure
  (ii)  secrets: `sk-` keys that are not test sentinels, gh[pousr]_ / hf_ tokens, AWS access key ids, private key
        blocks; with --exact-key-file, any occurrence of a value from that file (the value is never printed or
        written: the report names the file and the count only)                           -> failure
  (iii) forbidden paths (secrets, raw data, local runs, caches, zh-TW documents)            -> failure
  (iv)  relative Markdown links whose target is not in the export                           -> failure
        repository paths written in backticks that are not in the export                   -> notice
  (v)   absolute local paths (a Windows user profile, /home/<name>, /Users/<name>); scripts/redact_local_paths.py
        replaces them in evidence files and logs it in release/REDACTIONS.json         -> failure
  (vi)  sizes: total, per category, per top-level folder, the largest files                -> notice
A manifest entry that matches no file fails unless it is marked optional (`?`). DIR must not exist; it is left in
place when a gate fails so the hits can be inspected. Exit 0 when every failing gate is clean, 1 otherwise, 2 on
a usage error. Never initialises git, commits or pushes.
"""
from __future__ import annotations

import argparse
import datetime as dt
import fnmatch
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "kindredrelay-public-export-v1"
CATEGORIES = ("deploy", "verify", "evidence", "submission", "meta")
GENERATED = {"README.md": "README.md", "DEPLOY.md": "DEPLOY.md", "EVIDENCE.md": "EVIDENCE.md", "LICENSE": "LICENSE"}

CJK = re.compile("[\u3000-\u9fff\uf900-\ufaff\uff00-\uffef]")
# Never exported, whatever the manifest says. Matched against the repository-relative posix path.
FORBIDDEN = (
    (".git/**", "version control internals"), (".venv/**", "local virtual environment"),
    (".claude/**", "agent configuration"), (".remember/**", "agent memory"),
    (".streamlit/**", "holds a live API key"), ("**/secrets.toml", "secret store"),
    ("data/**", "raw datasets (git-ignored; redistribution not allowed)"),
    ("handoff_day1/data/**", "raw datasets"), ("release/validation_abd/**", "local validation runs (git-ignored)"),
    ("KindredRelay_Research_20261017/**", "audit copy of another branch"),
    ("**/__pycache__/**", "bytecode cache"), ("**/*.pyc", "bytecode cache"), ("**/desktop.ini", "OS metadata"),
    ("**/.env", "environment file"), ("**/*.env", "environment file"), ("**/.env.*", "environment file"),
    ("**/*.pem", "key file"), ("**/*.key", "key file"), ("**/kaggle.json", "Kaggle credentials"),
    ("**/*_zh-TW.md", "zh-TW document (English-only export)"), ("**/.kindredrelay-private/**", "private store"),
)
SECRET_PATTERNS = (
    ("openai_style_key", re.compile(r"(?<![A-Za-z0-9])sk-[A-Za-z0-9_\-]{16,}")),
    ("github_token", re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}")),
    ("huggingface_token", re.compile(r"hf_[A-Za-z0-9]{20,}")),
    ("aws_access_key_id", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("private_key_block", re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----")),
)
SENTINEL_WORDS = ("sentinel", "test", "not-a", "fake", "dummy", "example", "placeholder", "xxxx", "redacted")
ABS_PATH = re.compile(r"(?i)\b[a-z]:[\\/]+users[\\/]+[^\s\"'`)<>|]+|(?<![\w.])/(?:home|Users)/[a-z0-9._-]+/[^\s\"'`)<>|]*")
MD_LINK = re.compile(r"!?\[[^\]\n]*\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
MD_REF = re.compile(r"^\s{0,3}\[[^\]\n]+\]:\s*<?(\S+?)>?(?:\s+.*)?$", re.M)
TICK_PATH = re.compile(r"`((?:release|research|scripts|handoff_day1|deploy|training|submission|docs|artifacts|"
                       r"\.github)/[A-Za-z0-9_./\-]+?)(?::[0-9][0-9,\-]*)?`")


def posix(path: Path, base: Path) -> str:
    return path.relative_to(base).as_posix()


def glob_match(rel: str, pattern: str) -> bool:
    """`**` spans folders (including none), `*`/`?` stay within one name; matching is case-sensitive."""
    regex, i = "", 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            regex, i = regex + "(?:[^/]+/)*", i + 3
        elif pattern.startswith("**", i):
            regex, i = regex + ".*", i + 2
        elif pattern[i] == "*":
            regex, i = regex + "[^/]*", i + 1
        elif pattern[i] == "?":
            regex, i = regex + "[^/]", i + 1
        else:
            regex, i = regex + re.escape(pattern[i]), i + 1
    return re.fullmatch(regex, rel) is not None


def forbidden_reason(rel: str) -> str | None:
    for pattern, reason in FORBIDDEN:
        if glob_match(rel, pattern) or glob_match(rel, pattern.removeprefix("**/")):
            return reason
    return None


def read_manifest(path: Path) -> list[dict]:
    entries = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        parts = [p.strip() for p in line.split("|", 2)]
        if len(parts) != 3 or not all(parts):
            raise ValueError(f"{path.name}:{number}: expected '<category> | <glob> | <reason>'")
        category, pattern, reason = parts
        if category not in CATEGORIES:
            raise ValueError(f"{path.name}:{number}: unknown category {category!r}")
        optional, exclude = pattern.startswith("?"), pattern.startswith("!")
        pattern = pattern.lstrip("?!")
        if pattern.startswith("/") or ".." in PurePosixPath(pattern).parts or "\\" in pattern:
            raise ValueError(f"{path.name}:{number}: glob must be repository-relative with forward slashes")
        entries.append({"line": number, "category": category, "glob": pattern, "reason": reason,
                        "optional": optional, "exclude": exclude})
    return entries


def read_allowlist(path: Path) -> dict[str, dict]:
    """path -> {"reason", "chars"}: chars is the set of CJK characters allowed there (None: any)."""
    allowed = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip() and not line.lstrip().startswith("#"):
                parts = [p.strip() for p in line.split("|")]
                chars = next((p.removeprefix("chars=") for p in parts[2:] if p.startswith("chars=")), None)
                allowed[parts[0]] = {"reason": parts[1] if len(parts) > 1 else "",
                                     "chars": set(chars) if chars is not None else None}
    return allowed


def repo_files(root: Path) -> list[str]:
    """Every file under root, skipping folders that are never exported (fast path for .git and .venv)."""
    out, skip = [], {".git", ".venv", "__pycache__", ".claude", ".remember", ".streamlit"}
    stack = [root]
    while stack:
        folder = stack.pop()
        for child in folder.iterdir():
            if child.is_dir():
                if child.name not in skip and not child.is_symlink():
                    stack.append(child)
            elif child.is_file():
                out.append(posix(child, root))
    return sorted(out)


def select(root: Path, entries: list[dict]) -> tuple[dict[str, dict], list[dict], list[dict]]:
    files = repo_files(root)
    chosen, refused, unmatched = {}, [], []
    for entry in entries:
        hits = [f for f in files if glob_match(f, entry["glob"])]
        entry["matches"] = len(hits)
        if not hits:
            unmatched.append(entry)
        for rel in hits:
            if entry["exclude"]:
                chosen.pop(rel, None)
                continue
            reason = forbidden_reason(rel)
            if reason:
                refused.append({"path": rel, "reason": reason, "manifest_line": entry["line"]})
            elif rel in GENERATED:
                refused.append({"path": rel, "reason": "written from public_repo/ at the export root",
                                "manifest_line": entry["line"]})
            else:
                chosen.setdefault(rel, entry)
    return chosen, refused, unmatched


def text_of(path: Path) -> str | None:
    data = path.read_bytes()
    if b"\x00" in data[:8192]:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def is_sentinel(token: str) -> bool:
    low = token.lower()
    return any(word in low for word in SENTINEL_WORDS)


def key_values(path: Path) -> list[str]:
    """Candidate secret values in a key file: `name = "value"` entries, else whole lines; 8+ characters only."""
    values = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("["):
            continue
        if "=" in line:
            line = line.split("=", 1)[1].strip()
        line = line.strip("\"'")
        if len(line) >= 8:
            values.append(line)
    return values


def line_of(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


def link_target(md_rel: str, target: str, out: Path) -> str | None:
    """Export-relative posix path a relative link points at, or None for URLs, anchors and mail links."""
    target = target.split("#", 1)[0].split("?", 1)[0]
    if not target or re.match(r"(?i)^[a-z][a-z0-9+.\-]*:", target) or target.startswith("//"):
        return None
    base = PurePosixPath(md_rel).parent
    parts = []
    for part in (PurePosixPath(target.lstrip("/")) if target.startswith("/") else base / target).parts:
        if part == "..":
            if not parts:
                return "../" + target
            parts.pop()
        elif part != ".":
            parts.append(part)
    return "/".join(parts)


def gates(out: Path, allow: dict[str, dict], key_file: Path | None, categories: dict[str, str]) -> dict:
    staged = [posix(p, out) for p in sorted(out.rglob("*")) if p.is_file() and p.name != "EXPORT_REPORT.json"]
    present = set(staged)
    folders = {str(parent) for p in staged for parent in PurePosixPath(p).parents if str(parent) != "."}
    cjk, cjk_allowed, secrets, sentinels, forbidden, dangling, cited_missing, abs_paths = [], [], [], [], [], [], [], []
    exact = key_values(key_file) if key_file else []
    exact_hits = []
    for rel in staged:
        reason = forbidden_reason(rel)
        if reason:
            forbidden.append({"path": rel, "reason": reason})
        data = (out / rel).read_bytes()
        for value in exact:
            count = data.count(value.encode("utf-8"))
            if count:
                exact_hits.append({"path": rel, "occurrences": count})
        text = text_of(out / rel)
        if text is None:
            continue
        hits = [(line_of(text, m.start()), m.group()) for m in CJK.finditer(text)]
        entry = allow.get(rel)
        if hits and entry:
            outside = [(n, c) for n, c in hits if entry["chars"] is not None and c not in entry["chars"]]
            lines = sorted({n for n, _ in hits})
            cjk_allowed.append({"path": rel, "characters": len(hits), "lines": lines[:20], "line_count": len(lines),
                                "reason": entry["reason"]})
            hits = outside      # characters the allowlist entry does not name still fail
        if hits:
            lines = sorted({n for n, _ in hits})
            cjk.append({"path": rel, "characters": len(hits), "lines": lines[:20], "line_count": len(lines)})
        for name, pattern in SECRET_PATTERNS:
            for m in pattern.finditer(text):
                row = {"path": rel, "line": line_of(text, m.start()), "pattern": name,
                       "redacted": m.group()[:4] + "…" + f"({len(m.group())} chars)"}
                (sentinels if name == "openai_style_key" and is_sentinel(m.group()) else secrets).append(row)
        for m in ABS_PATH.finditer(text):
            abs_paths.append({"path": rel, "line": line_of(text, m.start()), "text": m.group()[:120]})
        if rel.endswith(".md"):
            for m in list(MD_LINK.finditer(text)) + list(MD_REF.finditer(text)):
                target = link_target(rel, m.group(1), out)
                if target is not None and target not in present and target.rstrip("/") not in folders:
                    dangling.append({"path": rel, "line": line_of(text, m.start()), "link": m.group(1)})
            for m in TICK_PATH.finditer(text):
                cited = m.group(1).rstrip("/.")
                if "*" in cited or cited in present or cited in folders:
                    continue
                if any(p.startswith(cited) for p in present):   # a name prefix such as release/benchmarks/tf_bench_
                    continue
                cited_missing.append({"path": rel, "line": line_of(text, m.start()), "cited": cited})
    for entry in allow:
        if entry not in present:
            cjk_allowed.append({"path": entry, "characters": 0, "note": "allowlisted but not exported"})
    sizes = {rel: (out / rel).stat().st_size for rel in staged}
    by_top, by_category = {}, {}
    for rel, size in sizes.items():
        top = rel.split("/", 1)[0] if "/" in rel else "(root)"
        by_top.setdefault(top, [0, 0])
        by_top[top][0] += 1
        by_top[top][1] += size
        cat = categories.get(rel, "meta")
        by_category.setdefault(cat, [0, 0])
        by_category[cat][0] += 1
        by_category[cat][1] += size
    return {
        "cjk": {"failing": cjk, "allowlisted": cjk_allowed, "passed": not cjk},
        "secrets": {"failing": secrets, "sentinels": sentinels, "passed": not secrets and not exact_hits,
                    "exact_key_file": key_file.name if key_file else None, "exact_values_checked": len(exact),
                    "exact_hits": exact_hits},
        "forbidden_paths": {"failing": forbidden, "passed": not forbidden},
        "links": {"dangling": dangling, "passed": not dangling, "cited_paths_not_exported": cited_missing},
        "absolute_local_paths": {"failing": abs_paths, "files": sorted({a["path"] for a in abs_paths}),
                                 "passed": not abs_paths},
        "sizes": {"files": len(sizes), "bytes": sum(sizes.values()),
                  "by_category": {k: {"files": v[0], "bytes": v[1]} for k, v in sorted(by_category.items())},
                  "by_top_level": {k: {"files": v[0], "bytes": v[1]} for k, v in sorted(by_top.items())},
                  "largest": [{"path": p, "bytes": s} for p, s in sorted(sizes.items(), key=lambda x: -x[1])[:15]]},
    }


def export(root: Path, public: Path, out: Path, key_file: Path | None) -> dict:
    entries = read_manifest(public / "MANIFEST.txt")
    allow = read_allowlist(public / "CJK_ALLOWLIST.txt")
    chosen, refused, unmatched = select(root, entries)
    missing_generated = [name for name in GENERATED.values() if not (public / name).is_file()]
    if missing_generated:
        raise FileNotFoundError("public_repo/ lacks " + ", ".join(missing_generated))
    out.mkdir(parents=True, exist_ok=False)
    categories = {}
    for rel, entry in sorted(chosen.items()):
        target = out / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / rel, target)
        categories[rel] = entry["category"]
    for dest, src in GENERATED.items():
        shutil.copyfile(public / src, out / dest)
        categories[dest] = "meta"
    result = gates(out, allow, key_file, categories)
    failing_unmatched = [e for e in unmatched if not e["optional"] and not e["exclude"]]
    passed = (result["cjk"]["passed"] and result["secrets"]["passed"] and result["forbidden_paths"]["passed"]
              and result["links"]["passed"] and result["absolute_local_paths"]["passed"] and not failing_unmatched)
    report = {
        "schema": SCHEMA, "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "source_folder": root.name, "out_folder": out.name, "passed": passed,   # names only: no local paths
        "manifest": {"entries": [{k: e[k] for k in ("line", "category", "glob", "optional", "exclude", "matches",
                                                     "reason")} for e in entries],
                     "unmatched_required": [{"line": e["line"], "glob": e["glob"]} for e in failing_unmatched],
                     "unmatched_optional": [{"line": e["line"], "glob": e["glob"]} for e in unmatched
                                            if e["optional"]],
                     "refused": refused},
        "files_sha256": {rel: hashlib.sha256((out / rel).read_bytes()).hexdigest()
                         for rel in sorted(categories)},
        "gates": result,
    }
    (out / "EXPORT_REPORT.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def summary_lines(report: dict) -> list[str]:
    g = report["gates"]
    return [
        f"files={g['sizes']['files']} bytes={g['sizes']['bytes']}",
        f"(i) cjk failing={len(g['cjk']['failing'])} allowlisted={len(g['cjk']['allowlisted'])}",
        f"(ii) secrets failing={len(g['secrets']['failing'])} exact_hits={len(g['secrets']['exact_hits'])} "
        f"sentinels={len(g['secrets']['sentinels'])} exact_values_checked={g['secrets']['exact_values_checked']}",
        f"(iii) forbidden={len(g['forbidden_paths']['failing'])} refused_by_selection={len(report['manifest']['refused'])}",
        f"(iv) dangling_links={len(g['links']['dangling'])} cited_paths_not_exported="
        f"{len(g['links']['cited_paths_not_exported'])}",
        f"(v) absolute_local_paths={len(g['absolute_local_paths']['failing'])} in "
        f"{len(g['absolute_local_paths']['files'])} files",
        f"manifest unmatched_required={len(report['manifest']['unmatched_required'])}",
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, required=True, help="staging folder; must not exist")
    parser.add_argument("--root", type=Path, default=ROOT, help="repository to export (default: this checkout)")
    parser.add_argument("--public", type=Path, default=None, help="manifest/templates folder (default: ROOT/public_repo)")
    parser.add_argument("--exact-key-file", type=Path, default=None,
                        help="file holding secret values to search for; values are never printed")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    public = (args.public or root / "public_repo").resolve()
    out = args.out.resolve()
    if out.exists():
        print(f"--out {out} already exists; choose a new folder", file=sys.stderr)
        return 2
    if out == root or root in out.parents:
        print("--out must be outside the repository", file=sys.stderr)
        return 2
    if args.exact_key_file is not None and not args.exact_key_file.is_file():
        print("--exact-key-file is not a readable file", file=sys.stderr)
        return 2
    try:
        report = export(root, public, out, args.exact_key_file)
    except (OSError, ValueError) as error:
        print(f"export error: {error}", file=sys.stderr)
        return 2
    for line in summary_lines(report):
        print(line)
    print(f"report: {out / 'EXPORT_REPORT.json'}")
    print(f"RESULT: {'PASS' if report['passed'] else 'FAIL'}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
