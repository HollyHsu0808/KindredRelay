#!/usr/bin/env python3
"""Replace this machine's absolute local paths in evidence files with placeholders and log every change.

python scripts/redact_local_paths.py FILE [FILE ...] [--log release/REDACTIONS.json] [--home DIR] [--repo DIR]

A path under the user profile (--home, default: this account's home folder) in any spelling (drive letter in either
case, `\\` or `/` separators, JSON-escaped `\\\\`, Git Bash `/<drive>/...`) becomes `<repo>/` + the part below the
repository root (--repo, default: this checkout) with `/` separators, or `<local>/…/` + its last component when it is
outside the repository (`<local>` for the profile folder itself). Nothing else changes: .json and .jsonl files are
rewritten only inside their path strings (the layout, key order and number text stay as they were) and must then
decode to the original document with exactly those strings replaced; every non-string value is checked to be
unchanged (values_sha256, a digest of the document's shape and non-string values, is the same before and after).
Other files are treated as text. Each changed file is added to --log (an entry per path: original and redacted
sha256, replacement count, values_sha256, UTC time) and --log with .md instead of .json is rewritten from it.
Results were computed before redaction; the log is how scripts/verify_claims.py accepts the documented hash change.
Exit 0 when done (also when nothing matched), 1 when a file cannot be redacted safely (nothing is written for it),
2 on a usage error. Stdlib only; no network.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "kindredrelay-redactions-v1"
REPO_TOKEN, LOCAL_TOKEN, ELLIPSIS = "<repo>", "<local>", "\u2026"
STOP = "\\s\"'`<>|)\\]},;"              # characters that end a path in JSON, Markdown and command lines
RULE = ("absolute paths under the user profile folder, in any spelling (drive letter in either case, \\ or / "
        "separators, JSON-escaped \\\\, Git Bash /<drive>/...): inside the repository root -> <repo>/ + the path below "
        "the root with / separators; elsewhere under the profile -> <local>/\u2026/ + the last path component (<local> "
        "for the profile folder itself). Nothing else changes.")
NOTE = ("The results in these files were produced before redaction. Only path strings changed; every number and other "
        "non-string value is unchanged, verified by values_sha256 (the same digest before and after) and recomputed by "
        "scripts/verify_claims.py.")
EXIT_OK, EXIT_UNSAFE, EXIT_USAGE = 0, 1, 2


class RedactError(Exception):
    """A file whose redaction could not be proven to change path strings only; it was not written."""


def utc() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


class Redactor:
    """Finds home in any spelling plus the rest of the path; repo (if under home) maps to <repo>."""

    def __init__(self, home: Path | str | None = None, repo: Path | str | None = None):
        home = str(home if home is not None else Path.home())
        repo = str(repo if repo is not None else ROOT)
        win = bool(re.match(r"^[A-Za-z]:", home))
        P = PureWindowsPath if win else PurePosixPath
        hp, rp = P(home), P(repo)
        parts = [re.escape(p) for p in hp.parts[1:]]
        if not parts:
            raise ValueError(f"--home {home!r} names no folder")
        sep, name = r"[\\/]+", f"[^{STOP}\\\\/]"
        if win:
            d = re.escape(hp.drive[0])
            lead = rf"(?:(?<![A-Za-z0-9]){d}:|(?<![\w.:])/{d}(?=[\\/]))" + sep
        else:
            lead = r"(?<![\w.])/"
        self.pattern = re.compile(lead + sep.join(parts) + f"(?=[{STOP}\\\\/]|$)(?P<rest>(?:{sep}{name}*)*)",
                                  re.IGNORECASE)
        try:
            self.repo_parts = [p.lower() for p in rp.relative_to(hp).parts] if win else list(rp.relative_to(hp).parts)
        except ValueError:
            self.repo_parts = None
        self.win = win

    def _sub(self, m: re.Match, escape_ellipsis: bool) -> str:
        comps = [c for c in re.split(r"[\\/]+", m.group("rest")) if c]
        head = [c.lower() if self.win else c for c in comps[:len(self.repo_parts or ())]]
        if self.repo_parts is not None and head == self.repo_parts:
            return "/".join([REPO_TOKEN] + comps[len(self.repo_parts):])
        if not comps:
            return LOCAL_TOKEN
        return "/".join([LOCAL_TOKEN, "\\u2026" if escape_ellipsis else ELLIPSIS, comps[-1]])

    def text(self, s: str, escape_ellipsis: bool = False) -> tuple[str, int]:
        """(s with every local path replaced, number replaced)."""
        return self.pattern.subn(lambda m: self._sub(m, escape_ellipsis), s)

    def obj(self, o, counter: list[int] | None = None):
        """A copy of a decoded JSON value with every string (keys too) redacted; counter[0] collects the count."""
        counter = counter if counter is not None else [0]
        if isinstance(o, str):
            s, n = self.text(o)
            counter[0] += n
            return s
        if isinstance(o, list):
            return [self.obj(v, counter) for v in o]
        if isinstance(o, dict):
            out = {}
            for k, v in o.items():
                k2 = self.obj(k, counter)
                if k2 in out:
                    raise RedactError(f"two keys become {k2!r} after redaction")
                out[k2] = self.obj(v, counter)
            return out
        return o


def shape(o):
    """The document without its strings: containers, sizes, order and every non-string value (exact JSON text)."""
    if isinstance(o, dict):
        return ["{", [shape(v) for v in o.values()]]
    if isinstance(o, list):
        return ["[", [shape(v) for v in o]]
    if isinstance(o, str):
        return "s"
    return ["v", json.dumps(o)]


def values_sha256(docs: list) -> str:
    return hashlib.sha256(json.dumps(shape(docs), separators=(",", ":")).encode("utf-8")).hexdigest()


def parse(text: str, kind: str) -> list:
    if kind == "jsonl":
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    return [json.loads(text)]


def canon(docs: list) -> str:
    return json.dumps(docs, ensure_ascii=False)     # type-exact: 1, 1.0 and true differ


def redump(docs: list, text: str, kind: str) -> str:
    """Fallback writer when an in-place rewrite does not decode to the expected document."""
    ascii_only = text.isascii()
    if kind == "jsonl":
        return "".join(json.dumps(d, ensure_ascii=ascii_only) + "\n" for d in docs)
    m = re.search(r"\n( +)\S", text)
    out = json.dumps(docs[0], ensure_ascii=ascii_only, indent=len(m.group(1)) if m else None)
    return out + ("\n" if text.endswith("\n") else "")


def redact_bytes(raw: bytes, suffix: str, r: Redactor) -> tuple[bytes, dict]:
    """(redacted bytes, facts) for one file's content; RedactError when the change is not path strings only."""
    text = raw.decode("utf-8")
    kind = {".json": "json", ".jsonl": "jsonl"}.get(suffix.lower(), "text")
    if kind == "text":
        new, n = r.text(text)
        return new.encode("utf-8"), {"format": kind, "replacements": n, "method": "in_place", "values_sha256": None}
    docs = parse(text, kind)
    counter = [0]
    expected = [r.obj(d, counter) for d in docs]
    new, _ = r.text(text, escape_ellipsis=text.isascii())
    method = "in_place"
    try:
        ok = canon(parse(new, kind)) == canon(expected)
    except ValueError:
        ok = False
    if not ok:
        new, method = redump(expected, text, kind), "redump"
        if canon(parse(new, kind)) != canon(expected):
            raise RedactError("the rewritten file does not decode to the redacted document")
    before, after = values_sha256(docs), values_sha256(parse(new, kind))
    if before != after:
        raise RedactError("a non-string value changed")
    return new.encode("utf-8"), {"format": kind, "replacements": counter[0], "method": method, "values_sha256": before}


def rel(path: Path, root: Path) -> str:
    try:
        return Path(path).resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return Path(path).name


def load_log(path: Path) -> dict:
    if path.is_file():
        log = json.loads(path.read_text(encoding="utf-8"))
        if log.get("schema") == SCHEMA:
            return log
    return {"schema": SCHEMA, "rule": RULE, "note": NOTE, "tool": "scripts/redact_local_paths.py", "files": []}


def markdown(log: dict) -> str:
    rows = "".join(f"| `{e['path']}` | {e['replacements']} | `{e['original_sha256']}` | `{e['redacted_sha256']}` | "
                   f"{e['values_sha256'] and '`' + e['values_sha256'][:12] + '`' or 'n/a (text)'} | {e['redacted_utc']} |\n"
                   for e in log["files"])
    return ("# Redactions of local paths\n\n"
            f"Written by `{log['tool']}` from [REDACTIONS.json](REDACTIONS.json).\n\n"
            f"Rule: `{log['rule']}`\n\n{log['note']}\n\n"
            "The Scorecard snapshots (`handoff_day1/ui/pages/shell/data/`) are redacted the same way when "
            "`scripts/freeze_scorecard_results.py` writes them; each records the count in `frozen.local_paths_redacted`."
            "\n\n"
            "| File | Paths replaced | Original sha256 | Redacted sha256 | values_sha256 (before = after) | UTC |\n"
            "|---|---|---|---|---|---|\n" + rows)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+", type=Path, help="files to redact in place")
    ap.add_argument("--log", type=Path, default=ROOT / "release" / "REDACTIONS.json", help="redaction log (JSON)")
    ap.add_argument("--home", default=None, help="user profile folder (default: this account's home)")
    ap.add_argument("--repo", type=Path, default=ROOT, help="repository root (default: this checkout)")
    args = ap.parse_args(argv)
    missing = [str(f) for f in args.files if not f.is_file()]
    if missing:
        print(f"redact_local_paths: not a file: {', '.join(missing)}", file=sys.stderr)
        return EXIT_USAGE
    r = Redactor(args.home, args.repo)
    log, code = load_log(args.log), EXIT_OK
    for f in args.files:
        raw = f.read_bytes()
        try:
            new, facts = redact_bytes(raw, f.suffix, r)
        except (RedactError, ValueError) as e:
            print(f"redact_local_paths: {rel(f, args.repo)}: not redacted ({e})", file=sys.stderr)
            code = EXIT_UNSAFE
            continue
        if facts["replacements"] == 0 or new == raw:
            print(f"{rel(f, args.repo)}: no local path")
            continue
        f.write_bytes(new)
        entry = {"path": rel(f, args.repo), "original_sha256": hashlib.sha256(raw).hexdigest(),
                 "redacted_sha256": hashlib.sha256(new).hexdigest(), **facts, "redacted_utc": utc()}
        log["files"] = [e for e in log["files"] if e["path"] != entry["path"]] + [entry]
        print(f"{entry['path']}: {facts['replacements']} paths replaced ({facts['method']}); sha256 "
              f"{entry['original_sha256'][:12]} -> {entry['redacted_sha256'][:12]}")
    log["files"].sort(key=lambda e: e["path"])
    args.log.parent.mkdir(parents=True, exist_ok=True)
    args.log.write_text(json.dumps(log, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    args.log.with_suffix(".md").write_text(markdown(log), encoding="utf-8")
    return code


if __name__ == "__main__":
    sys.exit(main())
