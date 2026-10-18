#!/usr/bin/env python3
"""Scan every blob reachable from all refs of a git repository for secrets. Offline, standard library and git only.

python scripts/scan_history_secrets.py REPO [KEY_FILE]

Prints only pattern names, blob paths and abbreviated blob ids, never a matched value. With KEY_FILE, the key in it
(whitespace stripped) is read into memory and every blob is also searched for that exact byte string
(EXACT_TOKEN_FACTORY_KEY); neither the key nor the key file's path is printed. The working tree, untracked files,
stashes and reflog-only objects are not scanned (only `git rev-list --all --objects`).
Exit 0 after a completed scan, hits or not (a record, as the session script it was copied from: the test files'
planted sentinel keys are pattern hits by design), 2 on a usage error; read the HIT lines.
"""
from __future__ import annotations

import collections
import os
import re
import subprocess
import sys

PATTERNS = {
    "openai_style_sk": re.compile(rb"\bsk-[A-Za-z0-9_\-]{20,}"),
    "github_token": re.compile(rb"\bgh[pousr]_[A-Za-z0-9]{30,}"),
    "hf_token": re.compile(rb"\bhf_[A-Za-z0-9]{30,}"),
    "aws_access_key": re.compile(rb"\bAKIA[0-9A-Z]{16}\b"),
    "private_key_block": re.compile(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    # [ \t]*, not \s*: a name at the end of a line ('token:') must not pair with the next line's text
    "assigned_api_key": re.compile(rb"(?i)(api[_-]?key|secret|password|token)[ \t]*[:=][ \t]*[\"']?[A-Za-z0-9_\-\.]{24,}"),
    "bearer_literal": re.compile(rb"(?i)bearer\s+[A-Za-z0-9_\-\.]{24,}"),
}
SUSPECT_NAMES = re.compile(r"(?i)(secrets\.toml|\.env$|\.env\.|id_rsa|\.pem$|\.key$|credentials|amd_api_key)")
PLACEHOLDER = re.compile(rb"(?i)(EMPTY|example|placeholder|your[_-]|xxxx|<|\$\{|REDACTED|dummy|sentinel|fake|test)")


def git(repo, *a, data=None):
    return subprocess.run(["git", "-C", repo, *a], input=data, capture_output=True, check=True).stdout


def blobs_of(repo) -> dict[str, set[str]]:
    """Object id -> the paths it appears under, for every object with a path reachable from any ref."""
    objs = git(repo, "rev-list", "--all", "--objects").decode("utf-8", "replace").splitlines()
    out: dict[str, set[str]] = {}
    for line in objs:
        parts = line.split(" ", 1)
        if len(parts) == 2:
            out.setdefault(parts[0], set()).add(parts[1])
    return out


def read_blobs(repo, shas: list[str]):
    """(sha, bytes) for each sha that is a blob, through one `git cat-file --batch`."""
    if not shas:
        return
    raw = git(repo, "cat-file", "--batch", data="".join(s + "\n" for s in shas).encode("ascii"))
    i = 0
    while i < len(raw):
        nl = raw.index(b"\n", i)
        head = raw[i:nl].split()
        i = nl + 1
        if len(head) < 3:          # '<sha> missing'
            continue
        size = int(head[2])
        body = raw[i:i + size]
        i += size + 1              # the newline after each object
        if head[1] == b"blob":
            yield head[0].decode("ascii"), body


def scan(repo, key: bytes | None = None) -> dict:
    blobs = blobs_of(repo)
    hits = collections.defaultdict(set)
    names = set()
    n_blobs = 0
    for sha, data in read_blobs(repo, sorted(blobs)):
        n_blobs += 1
        paths = blobs[sha]
        for p in paths:
            if SUSPECT_NAMES.search(p):
                names.add(p)
        if key and key in data:
            for p in paths:
                hits[("EXACT_TOKEN_FACTORY_KEY", p)].add(sha[:10])
        for name, rx in PATTERNS.items():
            for m in rx.finditer(data):
                if name in ("assigned_api_key", "bearer_literal") and PLACEHOLDER.search(m.group(0)):
                    continue
                for p in paths:
                    hits[(name, p)].add(sha[:10])
    return {"objects": len(blobs), "blobs": n_blobs, "names": sorted(names), "hits": hits}


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv or len(argv) > 2 or argv[0].startswith("-"):
        print(__doc__.strip().splitlines()[2], file=sys.stderr)
        return 2
    repo = argv[0]
    key = None
    if len(argv) > 1 and os.path.exists(argv[1]):
        with open(argv[1], "rb") as fh:
            key = fh.read().strip() or None
    res = scan(repo, key)
    print(f"objects with a path: {res['objects']}; blobs scanned: {res['blobs']}; "
          f"exact-key check: {'on' if key else 'off'}")
    print("suspicious file names:", res["names"] or "none")
    if not res["hits"]:
        print("pattern hits: none")
    for (name, p), shas in sorted(res["hits"].items()):
        print(f"HIT {name}\t{p}\tblobs={','.join(sorted(shas))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
