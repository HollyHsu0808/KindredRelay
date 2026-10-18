# Secret scan of the git histories (2026-10-18, about 02:01 UTC)

Run by `scripts/scan_history_secrets.py` (sha256 `59ccaa47cf94db5a57014535d260d162695c1a9cb82df9bec24670738502781c`), offline, standard library and git only. Tests: `scripts/test_scan_history_secrets.py` (6 tests, run in a throwaway git repository).

| File | Repository scanned | Refs | Result |
|---|---|---|---|
| `local_history.txt` | this repository (KindredRelay_ABD), all local refs; HEAD `0874ecde81ab4acf3a48c9967a8c932522cb6b91` | every ref `git rev-list --all` reaches | 704 blobs; no exact-key hit; 4 pattern hits, all planted test sentinels (below) |
| `carerelay_history.txt` | a bare mirror clone of `https://github.com/HollyHsu0808/CareRelay.git` (the earlier public repository), in a session scratchpad | `refs/heads/main` `bc37ea8`, `refs/heads/HackathonDepolyment` `b8a53da`, `refs/heads/claude/tokenfactory-client` `bbbec2a` | 862 blobs; no exact-key hit; no pattern hit |

Commands (the second argument is a key file outside every repository; its path is not recorded here):

```bash
.venv/Scripts/python.exe -I -S scripts/scan_history_secrets.py .                 <KEY_FILE>  > local_history.txt
.venv/Scripts/python.exe -I -S scripts/scan_history_secrets.py <carerelay_mirror> <KEY_FILE>  > carerelay_history.txt
```

## What is checked

- **Scope:** every blob reachable from any ref (`git rev-list --all --objects`), i.e. every version of every file in every branch and tag of the history, including files deleted later. Not scanned: the working tree, untracked or ignored files (for example `.streamlit/secrets.toml`, which is git-ignored and was never committed), stashes, reflog-only objects, and any copy outside these two repositories.
- **Exact-key check:** the AMD Token Factory key the project used is read from its private key file into memory (whitespace stripped) and every blob is searched for that exact byte string. A hit is printed as `EXACT_TOKEN_FACTORY_KEY` with the path and blob id only. Neither scan has such a hit: the key is in no committed version of any file in either history.
- **Patterns** (names as printed): `openai_style_sk` (`sk-` and 20 or more key characters), `github_token`, `hf_token`, `aws_access_key`, `private_key_block`, `assigned_api_key` (`api_key` / `secret` / `password` / `token`, then `:` or `=`, then 24 or more key characters, on the same line), `bearer_literal`. The last two skip a match that contains a placeholder word (example, placeholder, dummy, sentinel, fake, test, REDACTED, ...). File names that look like secret stores (`secrets.toml`, `.env`, `.pem`, `.key`, `id_rsa`, `credentials`, `amd_api_key`) are listed separately.
- **Output:** pattern names, paths and 10-character blob ids only, never a matched value.

## The 4 local pattern hits

All four are `openai_style_sk` matches in test files: `handoff_day1/agent/test_llm_client_recorder.py:23`, `handoff_day1/ui/test_app_shell.py:39`, `scripts/test_bench_tf_handover.py:22`, `scripts/test_freeze_scorecard_results.py:50` (line numbers in the scanned blob). Each is a planted sentinel that the redaction tests require never to reach an output (`submission/SOURCES.md` row K01); each contains a placeholder word (checked by a separate in-memory pass that printed only the line, the length and whether such a word is present, not the value), and the exact-key check shows none of them is the real key. `deploy/release.env.example` (and its copy under `KindredRelay_Research_20261017/github_audit/`) is listed as a suspicious name; it is a template.

## Limits

- Pattern matching finds key-shaped strings only; a secret of another shape (a password in prose, a key split across lines or encoded) is not found. The exact-key check covers only the one key in the key file.
- The mirror is as fetched into the scratchpad earlier in this session; later pushes to that repository are not covered.
- The exit code is 0 after a completed scan whether or not there are hits (the planted sentinels are hits by design); read the `HIT` lines. CI runs the scan without a key file, so only the pattern and name checks run there.
- A clean history does not show that a key was never exposed elsewhere (a terminal, a log, a screenshot, a hosted endpoint's records).
