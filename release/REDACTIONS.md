# Redactions of local paths

Written by `scripts/redact_local_paths.py` from [REDACTIONS.json](REDACTIONS.json).

Rule: `absolute paths under the user profile folder, in any spelling (drive letter in either case, \ or / separators, JSON-escaped \\, Git Bash /<drive>/...): inside the repository root -> <repo>/ + the path below the root with / separators; elsewhere under the profile -> <local>/…/ + the last path component (<local> for the profile folder itself). Nothing else changes.`

The results in these files were produced before redaction. Only path strings changed; every number and other non-string value is unchanged, verified by values_sha256 (the same digest before and after) and recomputed by scripts/verify_claims.py.

The Scorecard snapshots (`handoff_day1/ui/pages/shell/data/`) are redacted the same way when `scripts/freeze_scorecard_results.py` writes them; each records the count in `frozen.local_paths_redacted`.

| File | Paths replaced | Original sha256 | Redacted sha256 | values_sha256 (before = after) | UTC |
|---|---|---|---|---|---|
| `release/benchmarks/redteam_20261017T140024Z/results.json` | 1 | `e434304a3b3dda997e7323ccb42a4bb8639ee35e99a33a53c57d692a08d2d716` | `929c1f86ff07139a47ae5dabd4e7d1852de3bc8207ccb3dbf838e17a0d4a61e7` | `54eddc738da3` | 2026-10-18T03:06:39+00:00 |
| `release/benchmarks/redteam_before_20261017T122640Z/results.json` | 1 | `3d92ee55466bbc1b7ebb669bd5190369afa8b6aa2158e9c489980fa6f9489692` | `fad1b5202d3c34d4a5e11afda5db6a677e82a6da04b1998e55f176784b276ffc` | `37ec38df4d44` | 2026-10-18T03:06:39+00:00 |
| `release/benchmarks/redteam_final_20261018T015005Z/results.json` | 1 | `957b08798bc72a0382c737a9b6dcf17baeda01c1dc4f45b48d3953e86ed30acf` | `eb9ff56f9ce70485ea0f1989f2bc66953b392fa039515482ffa4c6a99f9d6a9b` | `b45493a822ae` | 2026-10-18T03:06:39+00:00 |
| `release/benchmarks/redteam_final_20261018T024113Z/results.json` | 1 | `ea987f58b341cbd7fe19d8818ebe544d0803443658c2b3e61804a5368963ba0e` | `70c491bdf74c1591fb9297fd5a4bbf87345bb6271a8b940fa19ae23d4df68def` | `b45493a822ae` | 2026-10-18T03:06:39+00:00 |
| `release/benchmarks/tf_bench_20261017T124039Z/records.jsonl` | 1 | `ddf655b02a6bb3b9225accb4d6faa12a5850a80df5e3e312c085942a3d61894c` | `70183c0e67f7089435a33dad226ce7c2b060611a57a017c666c92e65d5980795` | `8af0a4338576` | 2026-10-18T03:06:39+00:00 |
| `release/benchmarks/tf_bench_20261017T124039Z/results.json` | 1 | `97df164240abdf9727cdd526c77faa4dfb0b96135aa5701f8f07e554fc5e9b0f` | `a8cfaf64d88c80f6d28e9c021a4d3d12e7aa397544b3ccfbdefad00d7f1da7a3` | `012f24cc13ff` | 2026-10-18T03:06:39+00:00 |
| `research/temporal_benchmark/results/round1_dev_20261017.json` | 1 | `d1a4a70ba18490e3608d137974ddbb184da6cb488a607b24167574bef989a93b` | `a3347c3959ed70d3ed1d0e8893a32b64165485c3b96005b307067c04eadbac24` | `aaaaf66fcafa` | 2026-10-18T03:06:39+00:00 |
