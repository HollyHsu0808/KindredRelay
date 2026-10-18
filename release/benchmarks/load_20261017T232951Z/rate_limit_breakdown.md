# HTTP 429 breakdown: `DeepSeek-V4-Flash` load run

Derived after the run (2026-10-17T23:41:06.663+00:00) from `release/benchmarks/load_20261017T232951Z/records.jsonl` (sha256 `77347998890e86f2f730a78486a857d8065eb3c0ce06480703659d6099022a8c`) only: derived after the run from records.jsonl alone (the HTTP records' redacted 429 bodies, at most 300 characters each); no model or endpoint was called and results.json / summary.md were not changed.

- Run started (UTC) 2026-10-17T23:29:52.312+00:00, endpoint host developer.amd.com.cn; 21 of 85 HTTP attempts answered 429: 17 x `rate_limit_exceeded`, 3 x `token_rate_limit_exceeded`, 1 x `process_concurrency_rate_limit_exceeded`.

| Concurrency | level window (UTC) | 429s / attempts | by code (message) | first / last 429 (UTC) |
|---|---|---|---|---|
| 1 | 2026-10-17T23:29:52.433+00:00 to 2026-10-17T23:32:25.919+00:00 | 0/16 | none | n/a |
| 2 | 2026-10-17T23:32:35.941+00:00 to 2026-10-17T23:33:56.278+00:00 | 0/16 | none | n/a |
| 4 | 2026-10-17T23:34:06.300+00:00 to 2026-10-17T23:35:03.309+00:00 | 1/17 | 1 x `process_concurrency_rate_limit_exceeded` (Model API rate limit exceeded; please retry later) | 2026-10-17T23:34:46.589+00:00 / 2026-10-17T23:34:46.589+00:00 |
| 8 | 2026-10-17T23:35:13.328+00:00 to 2026-10-17T23:36:54.474+00:00 | 20/36 | 17 x `rate_limit_exceeded` (Rate limit exceeded: maximum 20 requests per minute for this OneClick user. Please try again later.); 3 x `token_rate_limit_exceeded` (Model API rate limit exceeded; please retry later) | 2026-10-17T23:35:18.175+00:00 / 2026-10-17T23:35:42.153+00:00 |

Every 429 (time, request, attempt, code, Retry-After, wait before the retry):

- concurrency 4: 2026-10-17T23:34:46.589+00:00 request 12 attempt 1 `process_concurrency_rate_limit_exceeded` Retry-After 1 wait 1.0 s
- concurrency 8: 2026-10-17T23:35:18.175+00:00 request 9 attempt 1 `rate_limit_exceeded` Retry-After 6 wait 6.0 s
- concurrency 8: 2026-10-17T23:35:20.111+00:00 request 10 attempt 1 `rate_limit_exceeded` Retry-After 4 wait 4.0 s
- concurrency 8: 2026-10-17T23:35:22.070+00:00 request 11 attempt 1 `rate_limit_exceeded` Retry-After 2 wait 2.0 s
- concurrency 8: 2026-10-17T23:35:22.101+00:00 request 12 attempt 1 `rate_limit_exceeded` Retry-After 2 wait 2.0 s
- concurrency 8: 2026-10-17T23:35:23.213+00:00 request 13 attempt 1 `rate_limit_exceeded` Retry-After 1 wait 1.0 s
- concurrency 8: 2026-10-17T23:35:23.694+00:00 request 14 attempt 1 `rate_limit_exceeded` Retry-After 1 wait 1.0 s
- concurrency 8: 2026-10-17T23:35:25.011+00:00 request 12 attempt 2 `rate_limit_exceeded` Retry-After 12 wait 12.0 s
- concurrency 8: 2026-10-17T23:35:25.085+00:00 request 11 attempt 2 `rate_limit_exceeded` Retry-After 12 wait 12.0 s
- concurrency 8: 2026-10-17T23:35:25.150+00:00 request 10 attempt 2 `rate_limit_exceeded` Retry-After 12 wait 12.0 s
- concurrency 8: 2026-10-17T23:35:25.151+00:00 request 13 attempt 2 `rate_limit_exceeded` Retry-After 12 wait 12.0 s
- concurrency 8: 2026-10-17T23:35:25.177+00:00 request 9 attempt 2 `rate_limit_exceeded` Retry-After 12 wait 12.0 s
- concurrency 8: 2026-10-17T23:35:25.615+00:00 request 14 attempt 2 `rate_limit_exceeded` Retry-After 11 wait 11.0 s
- concurrency 8: 2026-10-17T23:35:37.882+00:00 request 12 attempt 3 `rate_limit_exceeded` Retry-After 3 wait 3.0 s
- concurrency 8: 2026-10-17T23:35:38.037+00:00 request 10 attempt 3 `rate_limit_exceeded` Retry-After 3 wait 3.0 s
- concurrency 8: 2026-10-17T23:35:38.073+00:00 request 11 attempt 3 `rate_limit_exceeded` Retry-After 3 wait 3.0 s
- concurrency 8: 2026-10-17T23:35:38.134+00:00 request 9 attempt 3 `rate_limit_exceeded` Retry-After 3 wait 3.0 s
- concurrency 8: 2026-10-17T23:35:38.162+00:00 request 13 attempt 3 `rate_limit_exceeded` Retry-After 2 wait 2.0 s
- concurrency 8: 2026-10-17T23:35:42.044+00:00 request 10 attempt 4 `token_rate_limit_exceeded` Retry-After 60 wait 60.0 s
- concurrency 8: 2026-10-17T23:35:42.142+00:00 request 9 attempt 4 `token_rate_limit_exceeded` Retry-After 60 wait 60.0 s
- concurrency 8: 2026-10-17T23:35:42.153+00:00 request 11 attempt 4 `token_rate_limit_exceeded` Retry-After 60 wait 60.0 s
