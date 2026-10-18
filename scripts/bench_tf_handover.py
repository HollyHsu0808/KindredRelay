#!/usr/bin/env python3
"""Reproducible benchmark of the family timeline's handover step on an OpenAI-compatible endpoint (by default the AMD
Token Factory endpoint of deploy/release.env.example).

One case is one update of the demo story (handoff_day1/care_cases/episode_hip_fracture.json, or CARERELAY_STORY) added
to the episode the way the release page adds a caregiver's update when a live model is connected
(ui/pages/1_Family_timeline.py: get_extractor() -> llm_extractor(make_client(max_tokens=2000)); add_verified() ->
Episode.add_update(update, extractor=..., evidence_checker=checker_from_env())). The story's earlier updates are first
replayed from their recorded extraction (no model), so the model sees the episode as the page would. The model proposes
facts, each quoting the update; episode.grounding_problem accepts or rejects every quote (the citation check) and the
optional evidence verifier (evidence_gate, KINDRED_VERIFIER_MODE; off in the release settings) may hold facts for
review. Nothing of that pipeline is copied here: it is imported and called. Cases are the story's first N updates in
file order (chronological); they are interleaved across models (repeat, case, model) so drift hits every model alike.

Measured per HTTP attempt: wall time, status, retry, and usage.prompt_tokens / completion_tokens exactly as the
endpoint returns them (null when absent: tokens are never estimated). Per case: end-to-end wall time of add_update
(including retries and backoff waits), LLM requests, tokens, success or failure class, facts proposed / accepted /
rejected by the grounding check / withheld by the gate, and the gate decision; the accepted facts (fact_id, type, quote)
and, since schema v2, the facts the grounding check rejected (type, quote, reason). The summary adds p50 / p95 / mean, a
percentile bootstrap 95% CI (stdlib random, fixed seed) for the median latency and the rates, and Wilson intervals.

Retries mirror llm_client: HTTP 429, transient 5xx and reset connections (llm_client.retry_reason), waits of 2, 4, 8, ...
s or the server's Retry-After (llm_client.retry_after_s), capped per wait; a timeout is not retried unless
CARERELAY_LLM_TIMEOUT_RETRIES allows it. Every attempt counts against --max-calls (this invocation's budget): when it is
reached the run stops cleanly, the case in progress is recorded as aborted, and --resume DIR continues the run.

The API key is read from --api-key-file (only the key in the file) or CARERELAY_LLM_API_KEY. It is sent only in the
Authorization header and is redacted (with any 8-character piece of it, and any Authorization / Bearer value) from
every record, error body, exception text, printed line and output file. results.json keeps the endpoint's host only,
and the stored command line has <redacted path> for the --api-key-file path.

Usage:
  python scripts/bench_tf_handover.py --dry-run --models A,B --cases 5 --out OUT       # no network: scripted fake
  python scripts/bench_tf_handover.py --list-models --api-key-file KEYFILE              # GET /models, ids only
  python scripts/bench_tf_handover.py --models DeepSeek-V4-Flash,Gemma-4-31B-IT --cases 12 --repeats 3 \\
      --ttft-probe 5 --api-key-file KEYFILE --out OUT
  python scripts/bench_tf_handover.py --resume OUT --api-key-file KEYFILE

Writes records.jsonl (appended as it happens), results.json, summary.md and latency.svg in OUT. Exit code 0 when the
run is complete, 3 when it stopped at --max-calls (resume it), 130 when interrupted, 2 for a usage problem. Stdlib only.
"""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import email.message
import hashlib
import http.client
import io
import json
import math
import os
from pathlib import Path
import random
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit
from xml.sax.saxutils import escape as xml_escape

ROOT = Path(__file__).resolve().parents[1]
AGENT = ROOT / "handoff_day1" / "agent"
sys.path.insert(0, str(AGENT))
from episode import Episode, llm_extractor, load_scenario, norm  # noqa: E402
from evidence_gate import checker_from_env  # noqa: E402
from llm_client import OpenAIChat, is_timeout, retry_after_s, retry_reason  # noqa: E402

SCHEMA_VERSION = "kindredrelay-bench-token-factory-v2"   # v2: case records add rejected_facts
READABLE_SCHEMA_VERSIONS = ("kindredrelay-bench-token-factory-v1", SCHEMA_VERSION)   # v1 results.json still validates
RELEASE_ENV = ROOT / "deploy" / "release.env.example"
DEFAULT_STORY = ROOT / "handoff_day1" / "care_cases" / "episode_hip_fracture.json"
FALLBACK_BASE_URL = "https://developer.amd.com.cn/radeon/api/v1"   # deploy/release.env.example line 1
FALLBACK_MODEL = "DeepSeek-V4-Flash"   # deploy/release.env.example line 2
TOKEN_FACTORY_HOST = "developer.amd.com.cn"
PAGE_MAX_TOKENS = 2000   # ui/pages/1_Family_timeline.py get_extractor(): make_client(max_tokens=2000)
BACKOFF_BASE_S = 2.0   # llm_client.urlopen_retrying: 2, 4, 8, ... s
TTFT_PROMPT = "Reply with the single word OK."
TTFT_MAX_TOKENS = 16
BOOTSTRAP_RESAMPLES = 2000
BOOTSTRAP_SEED = 20261017
BOOTSTRAP_MIN_N = 5   # fewer completed cases: no interval (null), not a misleading one
SOURCES = ("handoff_day1/agent/episode.py", "handoff_day1/agent/episode_events.py", "handoff_day1/agent/llm_client.py",
           "handoff_day1/agent/evidence_gate.py", "handoff_day1/ui/pages/1_Family_timeline.py",
           "scripts/bench_tf_handover.py")
CREDENTIAL_KEY = re.compile(r"secret|api.?key|authorization|credential|password", re.I)
KEY_FILE_FLAG = "--api-key-file"
REDACTED_PATH = "<redacted path>"
EXIT_OK, EXIT_USAGE, EXIT_PARTIAL, EXIT_INTERRUPTED = 0, 2, 3, 130


class UsageError(Exception):
    """A problem with the command line or the environment; nothing was sent."""


class CallBudgetExhausted(RuntimeError):
    """--max-calls HTTP attempts were made in this invocation."""


# ---------------------------------------------------------------------------------------------------------- secrets
class Redactor:
    """Removes the API key, any 8-character piece of it, and Authorization / Bearer values from text."""
    AUTH = re.compile(r"(?i)(authorization[\"']?\s*[:=]\s*[\"']?)(?:bearer\s+)?[^\s\"',;}]+")
    BEARER = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+")

    def __init__(self, secret: str | None = None):
        self.secret = secret if secret and len(secret) >= 4 else None

    def __call__(self, text) -> str:
        text = text if isinstance(text, str) else str(text)
        if self.secret:
            text = text.replace(self.secret, "[REDACTED]")
            if len(self.secret) >= 8:   # a server that echoes part of the key ("sk-abc...")
                spans = []
                for i in range(len(self.secret) - 7):
                    piece, start = self.secret[i:i + 8], 0
                    while (start := text.find(piece, start)) != -1:
                        spans.append((start, start + 8))
                        start += 1
                if spans:
                    spans.sort()
                    merged = [list(spans[0])]
                    for a, b in spans[1:]:
                        if a <= merged[-1][1]:
                            merged[-1][1] = max(merged[-1][1], b)
                        else:
                            merged.append([a, b])
                    out, pos = [], 0
                    for a, b in merged:
                        out += [text[pos:a], "[REDACTED]"]
                        pos = b
                    text = "".join(out) + text[pos:]
        text = self.AUTH.sub(lambda m: m.group(1) + "[REDACTED]", text)
        return self.BEARER.sub("Bearer [REDACTED]", text)


class RedactingStream:
    """sys.stdout / sys.stderr while the key is loaded: llm_client's own stderr lines and tracebacks pass through it."""

    def __init__(self, inner, redact: Redactor):
        self.inner, self.redact = inner, redact

    def write(self, s):
        self.inner.write(self.redact(s))
        return len(s)

    def flush(self):
        self.inner.flush()

    def __getattr__(self, name):
        return getattr(self.inner, name)


def load_api_key(path: str | None, env) -> str | None:
    """The key from a file holding only the key (whitespace stripped), else CARERELAY_LLM_API_KEY. Never printed."""
    if path:
        try:
            text = Path(path).read_text(encoding="utf-8-sig").strip()
        except OSError as e:
            raise UsageError(f"cannot read the API key file {path} ({type(e).__name__})") from None
        if not text or any(c.isspace() for c in text):
            raise UsageError(f"the API key file {path} must contain only the key (one line, no spaces)")
        return text
    return (env.get("CARERELAY_LLM_API_KEY") or "").strip() or None


def stored_argv(argv: list[str], redact) -> list[str]:
    """The command line as records.jsonl and results.json keep it: redacted, and the --api-key-file path (where the key
    lives on this machine) replaced by <redacted path>."""
    out, hide = [], False
    for a in argv:
        if hide:
            out.append(REDACTED_PATH)
        elif a.startswith(KEY_FILE_FLAG + "="):
            out.append(f"{KEY_FILE_FLAG}={REDACTED_PATH}")
        else:
            out.append(redact(a))
        hide = a == KEY_FILE_FLAG
    return out


def release_defaults(path: Path = RELEASE_ENV) -> dict:
    """KEY=VALUE lines of deploy/release.env.example (the release settings), the key line left out."""
    out = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return out
    for line in lines:
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = (x.strip() for x in line.split("=", 1))
            if k != "CARERELAY_LLM_API_KEY":
                out[k] = v
    return out


def check_base_url(url: str) -> str:
    u = urlsplit(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        raise UsageError("the base URL must be http(s)://host/... (the OpenAI-compatible one, ending in /v1)")
    if u.username or u.password or u.query or u.fragment:
        raise UsageError("the base URL must not carry credentials, a query or a fragment")
    return url.rstrip("/")


def endpoint_host(url: str) -> str:
    u = urlsplit(url)
    return (u.hostname or "") + (f":{u.port}" if u.port else "")


# ---------------------------------------------------------------------------------------------------------- transport
class Response:
    def __init__(self, status: int, headers: dict | None = None, body: bytes = b"", lines=None, raw=None):
        self.status, self.body, self._lines, self._raw = status, body, lines, raw
        self.headers = {str(k).lower(): v for k, v in (headers or {}).items()}

    def iter_lines(self):
        if self._raw is not None:
            while line := self._raw.readline():
                yield line
        else:
            yield from (self._lines if self._lines is not None else self.body.splitlines(keepends=True))

    def close(self):
        if self._raw is not None:
            self._raw.close()


class UrllibTransport:
    """One HTTP attempt with urllib. An HTTP error status raises urllib.error.HTTPError, as urlopen does."""
    name = "urllib"

    def __call__(self, method, url, headers, body, timeout, stream=False):
        t0 = time.perf_counter()
        r = urllib.request.urlopen(urllib.request.Request(url, data=body, method=method, headers=headers), timeout=timeout)
        status, hdrs = r.status, dict(r.headers.items())
        if stream:
            return Response(status, hdrs, raw=r)
        try:   # like llm_client: a reply still trickling in after the timeout is cut off
            chunks, read = [], getattr(r, "read1", r.read)
            while chunk := read(65536):
                chunks.append(chunk)
                if time.perf_counter() - t0 > timeout and not r.isclosed():
                    raise TimeoutError(f"the reply was still arriving after {timeout:g} s")
            if getattr(r, "length", None):
                raise http.client.IncompleteRead(b"".join(chunks), r.length)
        finally:
            r.close()
        return Response(status, hdrs, b"".join(chunks))


def _http_error(url, code, body: bytes, retry_after: str | None = None):
    hdrs = email.message.Message()
    hdrs["Content-Type"] = "application/json"
    if retry_after is not None:
        hdrs["Retry-After"] = retry_after
    return urllib.error.HTTPError(url, code, http.client.responses.get(code, "error"), hdrs, io.BytesIO(body))


class FakeTransport:
    """A deterministic OpenAI-compatible stand-in (dry runs and tests), not a model. Chat replies come from
    agent/fake_llm_server.respond (the scripted server's reply function, good mode): for the timeline's extraction
    prompt, the recorded facts of the story update whose text is in the prompt. usage is the fake server's own count
    (request bytes / 4, reply characters / 4). script: what to answer before the normal replies, in order: an HTTP
    status (int), {"status": 429, "retry_after": "1"}, "timeout" or "reset". omit_usage: replies carry no usage.
    stream_supported=False: a streaming request gets a whole JSON reply. require_key: answer 401 without that key;
    echo_auth_on_401: the 401 body repeats the Authorization header (as some gateways do, to test the redaction)."""
    name = "fake"

    def __init__(self, models=("fake-model",), *, script=None, omit_usage=False, stream_supported=True,
                 require_key=None, echo_auth_on_401=False, delay_s=None, fail_models=()):
        self.models, self.script = list(models), list(script or [])
        self.omit_usage, self.stream_supported = omit_usage, stream_supported
        self.require_key, self.echo_auth_on_401 = require_key, echo_auth_on_401
        self.delay_s, self.fail_models = delay_s, set(fail_models)
        self.calls = 0

    def _delay(self, model: str):
        # a few milliseconds that differ by model, so a dry run's chart has something to show; real time, not fake
        d = self.delay_s if self.delay_s is not None else 0.002 + hashlib.sha256(model.encode()).digest()[0] % 5 * 0.002
        if d:
            time.sleep(d)

    def __call__(self, method, url, headers, body, timeout, stream=False):
        self.calls += 1
        path = urlsplit(url).path.rstrip("/")
        auth = headers.get("Authorization", "")
        payload = json.loads(body) if body else {}
        model = payload.get("model") or ""
        if (self.require_key is not None and auth != f"Bearer {self.require_key}") or model in self.fail_models:
            msg = {"error": {"message": "invalid credentials" + (f" for header {auth}" if self.echo_auth_on_401 else "")}}
            raise _http_error(url, 401, json.dumps(msg).encode())
        if self.script:
            step = self.script.pop(0)
            if step == "timeout":
                raise TimeoutError("timed out")
            if step == "reset":
                raise ConnectionResetError("connection reset by peer")
            step = step if isinstance(step, dict) else {"status": step}
            raise _http_error(url, step["status"], b'{"error": {"message": "scripted"}}', step.get("retry_after"))
        if method == "GET" and path.endswith("/models"):
            return Response(200, {"Content-Type": "application/json"},
                            json.dumps({"object": "list", "data": [{"id": m, "object": "model"} for m in self.models]}).encode())
        if method != "POST" or not path.endswith("/chat/completions"):
            raise _http_error(url, 404, b'{"error": "not found"}')
        self._delay(model)
        if payload.get("stream"):
            if not self.stream_supported:
                return Response(200, {"Content-Type": "application/json"}, json.dumps(
                    {"choices": [{"index": 0, "message": {"role": "assistant", "content": "OK"}, "finish_reason": "stop"}]}).encode())
            events = [{"choices": [{"index": 0, "delta": {"role": "assistant"}}]},
                      {"choices": [{"index": 0, "delta": {"content": "OK"}}]},
                      {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}]
            lines = [b"data: " + json.dumps(e).encode() + b"\n\n" for e in events] + [b"data: [DONE]\n\n"]
            return Response(200, {"Content-Type": "text/event-stream"}, lines=lines)
        from fake_llm_server import respond   # agent/fake_llm_server.py, imported only for a fake run
        text = respond(payload)
        out = {"id": "fake", "object": "chat.completion", "model": model,
               "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}]}
        if not self.omit_usage:
            out["usage"] = {"prompt_tokens": len(body) // 4, "completion_tokens": max(1, len(text) // 4)}
        return Response(200, {"Content-Type": "application/json"}, json.dumps(out).encode())


# ---------------------------------------------------------------------------------------------------------- session
class CallBudget:
    def __init__(self, max_calls: int):
        self.max_calls, self.used = max_calls, 0

    def take(self):
        if self.used >= self.max_calls:
            raise CallBudgetExhausted(f"--max-calls {self.max_calls} reached")
        self.used += 1


class Meter:
    """What one case's HTTP attempts added up to."""

    def __init__(self):
        self.requests = self.attempts = self.retries = self.ok_calls = self.usage_missing = 0
        self.wait_s = 0.0
        self.prompt_tokens = self.completion_tokens = 0
        self.statuses: dict[str, int] = {}
        self.last: dict | None = None

    def add(self, rec: dict):
        self.attempts += 1
        self.retries += rec["attempt"] > 1
        self.wait_s += rec.get("wait_s") or 0.0
        key = str(rec.get("status"))
        self.statuses[key] = self.statuses.get(key, 0) + 1
        self.last = rec
        if rec["outcome"] == "ok":
            self.ok_calls += 1
            if isinstance(rec.get("prompt_tokens"), int) and isinstance(rec.get("completion_tokens"), int):
                self.prompt_tokens += rec["prompt_tokens"]
                self.completion_tokens += rec["completion_tokens"]
            else:
                self.usage_missing += 1


def usage_fields(usage) -> dict:
    """The reply's token counts as returned; None for anything absent or not a count. No estimates."""
    def count(name):
        v = usage.get(name) if isinstance(usage, dict) else None
        return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else None
    p, c, t = count("prompt_tokens"), count("completion_tokens"), count("total_tokens")
    if t is None and p is not None and c is not None:
        t = p + c
    return {"usage_present": isinstance(usage, dict), "prompt_tokens": p, "completion_tokens": c, "total_tokens": t}


class Session:
    """The one place that holds the key and makes HTTP attempts: retries, backoff, the call budget and one record per
    attempt (sink). ctx (model, case, repeat, purpose) is set by the runner before each case or probe."""

    def __init__(self, base_url, api_key, transport, budget, *, timeout_s, max_tries, max_wait_s, timeout_retries=0,
                 backoff_base_s=BACKOFF_BASE_S, sleep=time.sleep, sink=None, redact=None):
        self.base_url, self._api_key, self.transport, self.budget = base_url, api_key, transport, budget
        self.timeout_s, self.max_tries, self.max_wait_s = timeout_s, max(1, max_tries), max(0.0, max_wait_s)
        self.timeout_retries, self.backoff_base_s, self.sleep = max(0, timeout_retries), backoff_base_s, sleep
        self.sink, self.redact = sink or (lambda rec: None), redact or Redactor(api_key)
        self.ctx: dict = {}
        self.meter: Meter | None = None

    def __repr__(self):   # never the key
        return f"Session(host={endpoint_host(self.base_url)!r})"

    def begin(self, **ctx) -> Meter:
        self.ctx, self.meter = ctx, Meter()
        return self.meter

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        if self._api_key:
            h["Authorization"] = "Bearer " + self._api_key
        return h

    def log(self, rec: dict):
        rec.pop("_t0", None)
        if self.meter is not None:
            self.meter.add(rec)
        self.sink(rec)

    def send(self, method: str, path: str, payload: dict | None = None, *, stream: bool = False):
        """One request: up to max_tries attempts. Returns (response, record of the successful attempt, not yet logged:
        the caller adds what the reply says and calls log). The last failure is raised; an HTTPError keeps a readable,
        redacted body (llm_client.OpenAIChat.chat reads it)."""
        body = json.dumps(payload).encode() if payload is not None else None
        url = self.base_url + path
        if self.meter is not None:
            self.meter.requests += 1
        request_no = self.meter.requests if self.meter is not None else None
        waited, timeouts = 0.0, 0
        for attempt in range(1, self.max_tries + 1):
            self.budget.take()
            rec = {"type": "http", "ts": utc_now(), **self.ctx, "request": request_no, "attempt": attempt,
                   "method": method, "path": path, "stream": stream}
            t0 = time.perf_counter()
            try:
                resp = self.transport(method, url, self._headers(), body, self.timeout_s, stream=stream)
            except Exception as e:  # noqa: BLE001 - classified below; only retry_reason() cases and allowed timeouts retry
                wall = time.perf_counter() - t0
                status = e.code if isinstance(e, urllib.error.HTTPError) else None
                reason = retry_reason(e)
                timed_out = reason is None and is_timeout(e)
                timeouts += timed_out
                retry = attempt < self.max_tries and (reason is not None or (timed_out and timeouts <= self.timeout_retries))
                snippet, raise_as = None, e
                if isinstance(e, urllib.error.HTTPError):
                    try:
                        raw = e.read() or b""
                    except Exception:  # noqa: BLE001
                        raw = b""
                    clean = self.redact(raw.decode("utf-8", errors="replace"))
                    snippet = clean[:300]
                    hdrs = e.headers
                    try:
                        e.close()
                    except Exception:  # noqa: BLE001
                        pass
                    raise_as = urllib.error.HTTPError(url, e.code, e.msg, hdrs, io.BytesIO(clean.encode("utf-8")))
                outcome = ("timeout" if timed_out else "http_error" if status is not None else
                           "connection" if reason else "error")
                rec.update(status=status, wall_s=round(wall, 4), outcome=outcome, retryable=bool(reason) or timed_out,
                           error=self.redact(f"{type(e).__name__}: {e}")[:300], body=snippet)
                if retry:
                    hdr = e.headers.get("Retry-After") if isinstance(e, urllib.error.HTTPError) and e.headers else None
                    ra = retry_after_s(hdr)
                    wait = min(ra if ra is not None else self.backoff_base_s * 2 ** (attempt - 1), self.max_wait_s)
                    rec.update(wait_s=round(wait, 3), retry_after=hdr.strip()[:40] if hdr else None)
                    self.log(rec)
                    self.sleep(wait)
                    waited += wait
                    continue
                self.log(rec)
                if raise_as is e:
                    raise
                raise raise_as from None
            rec.update(status=resp.status, wall_s=round(time.perf_counter() - t0, 4), outcome="ok", waited_s=round(waited, 3),
                       _t0=t0)
            return resp, rec
        raise AssertionError("unreachable")


class InstrumentedChat(OpenAIChat):
    """llm_client.OpenAIChat with its HTTP layer (_request) replaced by Session.send. chat() itself (payload, guided or
    prompted JSON, the guided-JSON fallback, reply parsing) is the production code, unchanged. The key lives only in
    the Session, never on this object."""

    def __init__(self, session: Session, model: str, *, guided_json: bool, extra_body: dict,
                 max_tokens: int = PAGE_MAX_TOKENS):
        super().__init__(base_url=session.base_url, model=model, api_key="held-by-session", timeout_s=session.timeout_s,
                         max_tokens=max_tokens, max_tries=session.max_tries, max_wait_s=session.max_wait_s)
        self.session = session
        self.guided_json_supported = guided_json   # the page runs with CARERELAY_LLM_GUIDED_JSON=0 (release.env.example)
        self.extra_body = copy.deepcopy(extra_body)   # the run's recorded CARERELAY_LLM_EXTRA_BODY, also on a resume

    def _request(self, path: str, payload: dict | None = None) -> dict:
        method = "POST" if payload is not None else "GET"
        self.last_wait_s = self.last_attempt_s = 0.0
        resp, rec = self.session.send(method, path, payload)
        try:
            out = json.loads(resp.body)
        except ValueError:
            rec["outcome"] = "bad_json"
            self.session.log(rec)
            raise RuntimeError(f"the reply to {method} {path} is not JSON (is the base URL the OpenAI-compatible one, "
                               f"ending in /v1?): {self.session.redact(repr(resp.body[:200]))}") from None
        rec.update(usage_fields(out.get("usage") if isinstance(out, dict) else None))
        try:
            rec["finish_reason"] = out["choices"][0].get("finish_reason")
        except (KeyError, IndexError, TypeError, AttributeError):
            rec["finish_reason"] = None
        self.session.log(rec)
        self.last_wait_s, self.last_attempt_s = rec["waited_s"], rec["wall_s"]
        return out


# ---------------------------------------------------------------------------------------------------------- records
def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds")


class RecordWriter:
    """records.jsonl: one JSON line per event, appended and flushed as it happens, redacted."""

    def __init__(self, path: Path, redact: Redactor):
        self.path, self.redact = path, redact

    def write(self, rec: dict):
        line = self.redact(json.dumps(rec, ensure_ascii=False, sort_keys=True)).encode("utf-8")
        with open(self.path, "a+b") as f:
            f.seek(0, os.SEEK_END)
            prefix = b""
            if f.tell():   # a line cut off by an interruption: start on a fresh line
                f.seek(-1, os.SEEK_END)
                prefix = b"" if f.read(1) == b"\n" else b"\n"
            f.write(prefix + line + b"\n")
            f.flush()
            os.fsync(f.fileno())


def read_records(path: Path, skipped: list | None = None) -> list[dict]:
    """All records. A line that is not JSON (only an interrupted write makes one) is left out; its line number goes
    to skipped."""
    out = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            if skipped is not None:
                skipped.append(i)
    return out


RECORD_FIELDS = {
    "run_start": ("schema_version", "config", "invocation"),
    "invocation": ("invocation", "argv", "created_utc", "git", "source_sha256", "max_calls", "verifier_mode"),
    "invocation_end": ("invocation", "stopped_reason", "http_calls"),
    "http": ("invocation", "model", "purpose", "attempt", "method", "path", "status", "wall_s", "outcome"),
    "case": ("invocation", "model", "case_id", "repeat", "status", "failure_class", "e2e_s", "llm_requests",
             "http_attempts", "retries", "prompt_tokens", "completion_tokens", "total_tokens", "facts_proposed",
             "facts_accepted", "facts_rejected_grounding", "facts_withheld", "gate_mode", "gate_decision"),
    "ttft": ("model", "probe", "status", "stream_supported", "ttft_s", "total_s"),
}


def validate_record(rec) -> list[str]:
    if not isinstance(rec, dict) or rec.get("type") not in RECORD_FIELDS:
        return [f"unknown record type {rec.get('type') if isinstance(rec, dict) else type(rec).__name__}"]
    errs = [f"{rec['type']} record lacks {k}" for k in RECORD_FIELDS[rec["type"]] if k not in rec]
    if rec["type"] == "case" and rec.get("status") not in ("ok", "failed", "aborted"):
        errs.append(f"case status {rec.get('status')!r}")
    if rec["type"] == "case" and rec.get("gate_decision") not in ("off", "pass", "held", "shadow", None):
        errs.append(f"gate decision {rec.get('gate_decision')!r}")
    if rec["type"] == "case" and "rejected_facts" in rec:   # absent from v1 records
        rf = rec["rejected_facts"]
        if not (isinstance(rf, list) and all(isinstance(r, dict) and {"type", "quote", "reason"} <= set(r) for r in rf)):
            errs.append("rejected_facts is not a list of {type, quote, reason}")
    return errs


def rejected_fact(r: dict) -> dict:
    """A proposal the grounding check rejected, as a case record keeps it: its type and quote as the model gave them
    (None when not text; the quote cut at 300 characters) and episode.grounding_problem's reason."""
    f = r.get("fact") if isinstance(r, dict) else None
    f = f if isinstance(f, dict) else {}
    t, q = f.get("type"), f.get("quote")
    return {"type": t if isinstance(t, str) else None, "quote": q[:300] if isinstance(q, str) else None,
            "reason": r.get("reason") if isinstance(r, dict) else None}


# ---------------------------------------------------------------------------------------------------------- statistics
def percentile(xs, q: float):
    """Linear interpolation between closest ranks (numpy's default, statistics.quantiles 'inclusive'). None if empty."""
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    k = (len(xs) - 1) * q / 100.0
    f = math.floor(k)
    c = min(f + 1, len(xs) - 1)
    return xs[f] + (xs[c] - xs[f]) * (k - f)


def mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def bootstrap_ci(values, stat, *, key: str, resamples: int = BOOTSTRAP_RESAMPLES, seed: int = BOOTSTRAP_SEED,
                 min_n: int = BOOTSTRAP_MIN_N):
    """Percentile bootstrap 95% interval of stat over values (resampled with replacement). The generator is seeded from
    seed and key (a str seed is hashed with SHA-512 by random, so it does not depend on PYTHONHASHSEED). None when fewer
    than min_n values; resamples whose stat is None (e.g. no facts in any drawn case) are left out."""
    values = list(values)
    if len(values) < min_n:
        return None
    rng = random.Random(f"{seed}:{key}")
    n, stats = len(values), []
    for _ in range(resamples):
        s = stat([values[rng.randrange(n)] for _ in range(n)])
        if s is not None:
            stats.append(s)
    if not stats:
        return None
    return [round(percentile(stats, 2.5), 4), round(percentile(stats, 97.5), 4)]


def median(xs):
    return percentile(xs, 50)


def pooled(pairs):
    num, den = sum(a for a, _ in pairs), sum(b for _, b in pairs)
    return num / den if den else None


def wilson95(k: int, n: int):
    """Wilson score interval for k successes in n independent trials; None when n is 0."""
    if n <= 0:
        return None
    z, p = 1.959964, k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return [round(max(0.0, centre - half), 4), round(min(1.0, centre + half), 4)]


def rnd(x, n=4):
    return None if x is None else round(x, n)


# ---------------------------------------------------------------------------------------------------------- the run
def select_cases(scenario: dict, story_stem: str, n: int | None) -> list[dict]:
    updates = scenario.get("updates") or []
    if n is None:
        n = len(updates)
    if not 1 <= n <= len(updates):
        raise UsageError(f"--cases must be between 1 and {len(updates)} (the story's updates)")
    return [{"case_id": f"{story_stem}/{u['update_id']}", "index": i, "update": u} for i, u in enumerate(updates[:n])]


def failure_class(exc: BaseException | None, meter: Meter, log: dict) -> str | None:
    if exc is None:
        if not log:
            return "no_model_call"
        if not log.get("parsed"):
            return "truncated" if log.get("finish_reason") == "length" else "unparsed_reply"
        return None
    if isinstance(exc, CallBudgetExhausted):
        return "aborted_max_calls"
    last = meter.last or {}
    status = last.get("status")
    if status == 429:
        return "rate_limited"
    if status in (401, 403):
        return "auth"
    if isinstance(status, int) and status >= 500:
        return "server_error"
    if isinstance(status, int) and status >= 400:
        return "http_4xx"
    if last.get("outcome") in ("timeout", "connection", "bad_json"):
        return last["outcome"]
    return f"pipeline_error:{type(exc).__name__}"


def gate_decision(entry: dict | None, mode: str):
    """As evidence_gate defines it: 'off' (no verifier, the release setting), 'held' (gate mode withheld at least one
    fact for review, bind_check's withhold), 'pass' (gate mode, nothing withheld), 'shadow' (decisions recorded,
    nothing withheld by design). None when no entry was produced."""
    if entry is None:
        return None
    if mode == "off":
        return "off"
    if mode == "shadow":
        return "shadow"
    return "held" if any(c.get("withhold") for c in entry.get("evidence_checks") or []) else "pass"


def reference_match(accepted: list[dict], reference: list[dict]) -> int:
    """Heuristic, not a quality score: how many of the story's recorded facts (the fixture's curated extraction) have an
    accepted fact of the same type whose quote contains, or is contained in, the recorded quote (after episode.norm)."""
    hit = 0
    for r in reference:
        rq = norm(r.get("quote") or "")
        if rq and any(a.get("type") == r.get("type") and (aq := norm(a.get("quote") or "")) and (rq in aq or aq in rq)
                      for a in accepted):
            hit += 1
    return hit


class Bench:
    def __init__(self, cfg: dict, out: Path, *, transport, api_key: str | None, invocation: int, sleep=time.sleep,
                 checker="env", echo=print):
        self.cfg, self.out, self.invocation, self.echo = cfg, Path(out), invocation, echo
        self.redact = Redactor(api_key)
        self.writer = RecordWriter(self.out / "records.jsonl", self.redact)
        self.budget = CallBudget(cfg["max_calls"])
        self.session = Session(cfg["base_url"], api_key, transport, self.budget, timeout_s=cfg["timeout_s"],
                               max_tries=cfg["max_tries"], max_wait_s=cfg["max_wait_s"],
                               timeout_retries=cfg["timeout_retries"], backoff_base_s=cfg["backoff_base_s"], sleep=sleep,
                               sink=self.writer.write, redact=self.redact)
        self.checker = checker_from_env() if checker == "env" else checker
        self.gate_mode = "off" if self.checker is None else str(getattr(self.checker, "mode", "gate"))
        self.scenario = load_scenario(ROOT / cfg["story"])
        self.cases = [c for c in select_cases(self.scenario, Path(cfg["story"]).stem, len(cfg["case_ids"]))]
        if [c["case_id"] for c in self.cases] != cfg["case_ids"]:
            raise UsageError("the story's updates no longer match the run's case ids (was the story edited?)")
        self.clients = {m: InstrumentedChat(self.session, m, guided_json=cfg["guided_json"], extra_body=cfg["extra_body"])
                        for m in cfg["models"]}
        self._contexts: dict[int, Episode] = {}

    def context(self, index: int) -> Episode:
        """The episode after the story's first `index` updates, replayed from their recorded extraction (no model)."""
        if index not in self._contexts:
            ep = Episode(self.scenario)
            for u in self.scenario["updates"][:index]:
                ep.add_update(u, evidence_checker=self.checker)
            self._contexts[index] = ep
        return copy.deepcopy(self._contexts[index])

    def done(self) -> tuple[set, set]:
        recs = read_records(self.out / "records.jsonl")
        cases = {(r["model"], r["case_id"], r["repeat"]) for r in recs if r.get("type") == "case" and r["status"] != "aborted"}
        probes = {(r["model"], r["probe"]) for r in recs if r.get("type") == "ttft"}
        return cases, probes

    def run(self) -> str | None:
        cases_done, probes_done = self.done()
        plan = [(m, c, r) for r in range(self.cfg["repeats"]) for c in self.cases for m in self.cfg["models"]]
        todo = [p for p in plan if (p[0], p[1]["case_id"], p[2]) not in cases_done]
        probes = [(m, k) for k in range(self.cfg["ttft_probe"]) for m in self.cfg["models"] if (m, k) not in probes_done]
        self.echo(f"{len(plan) - len(todo)} of {len(plan)} cases already done; {len(todo)} to run, {len(probes)} TTFT probes; "
                  f"at most {self.cfg['max_calls']} HTTP calls in this invocation")
        try:
            for m, k in probes:
                self.ttft_probe(m, k)
            for i, (m, c, r) in enumerate(todo, 1):
                rec = self.run_case(m, c, r)
                facts = f"{rec['facts_accepted']}/{rec['facts_proposed']} facts accepted"
                toks = f"{rec['total_tokens']} tokens" if rec["total_tokens"] is not None else "tokens n/a"
                self.echo(f"[{i}/{len(todo)}] {m} {c['case_id']} r{r}: {rec['status']}"
                          + (f" ({rec['failure_class']})" if rec["failure_class"] else "")
                          + f", {rec['e2e_s']:.2f} s, {facts}, {toks}, {rec['retries']} retries")
        except CallBudgetExhausted:
            self.echo(f"stopped: --max-calls {self.cfg['max_calls']} reached; continue with --resume {self.out}")
            return "max_calls"
        return None

    def run_case(self, model: str, case: dict, repeat: int) -> dict:
        meter = self.session.begin(invocation=self.invocation, model=model, case_id=case["case_id"], repeat=repeat,
                                   purpose="extract")
        t_setup = time.perf_counter()
        ep = self.context(case["index"])
        setup_s = time.perf_counter() - t_setup
        update = {k: v for k, v in case["update"].items() if k != "recorded_extraction"}   # the model reads it live
        extractor = llm_extractor(self.clients[model])
        entry, exc = None, None
        t0 = time.perf_counter()
        try:
            entry = ep.add_update(update, extractor=extractor, evidence_checker=self.checker)
        except Exception as e:  # noqa: BLE001 - a model, network or pipeline problem is a measured failure, not a crash
            exc = e
        e2e = time.perf_counter() - t0
        log = extractor.log[-1] if extractor.log else {}
        fclass = failure_class(exc, meter, log)
        status = "aborted" if fclass == "aborted_max_calls" else "failed" if fclass else "ok"
        accepted = (entry or {}).get("facts") or []
        rejected = (entry or {}).get("rejected") or []
        withheld = [r for r in rejected if "verification" in r]
        grounding = [r for r in rejected if "verification" not in r]
        proposed = len(accepted) + len(rejected) if entry is not None else 0
        valid = proposed - len(grounding)
        checks = (entry or {}).get("evidence_checks") or []
        complete_usage = meter.ok_calls > 0 and meter.usage_missing == 0
        reference = case["update"].get("recorded_extraction") or []
        rec = {"type": "case", "ts": utc_now(), "invocation": self.invocation, "model": model, "case_id": case["case_id"],
               "update_id": case["update"]["update_id"], "kind": case["update"].get("kind"), "repeat": repeat,
               "status": status, "failure_class": fclass,
               "error": self.redact(f"{type(exc).__name__}: {exc}")[:500] if exc is not None else None,
               "e2e_s": round(e2e, 4), "e2e_excl_wait_s": round(max(0.0, e2e - meter.wait_s), 4),
               "setup_s": round(setup_s, 4), "llm_requests": meter.requests, "http_attempts": meter.attempts,
               "retries": meter.retries, "retry_wait_s": round(meter.wait_s, 3), "statuses": meter.statuses,
               "prompt_tokens": meter.prompt_tokens if complete_usage else None,
               "completion_tokens": meter.completion_tokens if complete_usage else None,
               "total_tokens": meter.prompt_tokens + meter.completion_tokens if complete_usage else None,
               "usage_complete": complete_usage, "calls_without_usage": meter.usage_missing,
               "json_mode": log.get("json_mode"), "finish_reason": log.get("finish_reason"), "reply_parsed": log.get("parsed"),
               "facts_proposed": proposed, "facts_accepted": len(accepted), "facts_rejected_grounding": len(grounding),
               "facts_withheld": len(withheld), "citations_valid": valid if entry is not None else None,
               "citation_validity": rnd(valid / proposed) if proposed else None,
               "rejection_reasons": [r.get("reason") for r in grounding],
               "rejected_facts": [rejected_fact(r) for r in grounding],
               "gate_mode": self.gate_mode, "gate_decision": gate_decision(entry, self.gate_mode),
               "verifier_statuses": sorted({c.get("status") for c in checks if c.get("status")}),
               "headline": (entry or {}).get("headline"),
               "accepted_facts": [{"fact_id": f.get("fact_id"), "type": f.get("type"), "quote": (f.get("quote") or "")[:300]}
                                  for f in accepted],
               "reference_facts": len(reference), "reference_matched": reference_match(accepted, reference) if entry else 0}
        self.writer.write(rec)
        if isinstance(exc, CallBudgetExhausted):
            raise exc
        return rec

    def ttft_probe(self, model: str, probe: int) -> dict:
        """Time to the first streamed token of a fixed short prompt. A server that does not stream is recorded, not a
        failure."""
        self.session.begin(invocation=self.invocation, model=model, case_id=None, repeat=None, purpose="ttft")
        payload = {"model": model, "messages": [{"role": "user", "content": TTFT_PROMPT}], "max_tokens": TTFT_MAX_TOKENS,
                   "temperature": 0.0, "stream": True, **self.clients[model].extra_body}
        rec = {"type": "ttft", "ts": utc_now(), "invocation": self.invocation, "model": model, "probe": probe,
               "status": None, "stream_supported": None, "ttft_s": None, "ttft_content_s": None, "first_byte_s": None,
               "total_s": None, "chunks": 0, "completion_tokens": None, "error": None}
        try:
            resp, http_rec = self.session.send("POST", "/chat/completions", payload, stream=True)
        except CallBudgetExhausted:
            raise
        except Exception as e:  # noqa: BLE001 - recorded; a probe never fails the run
            status = e.code if isinstance(e, urllib.error.HTTPError) else None
            rec.update(status=status, error=self.redact(f"{type(e).__name__}: {e}")[:300],
                       stream_supported=False if status in (400, 404, 405, 415, 422, 501) else None)
            self.writer.write(rec)
            return rec
        t0, rec["status"] = http_rec["_t0"], resp.status
        streaming = "text/event-stream" in (resp.headers.get("content-type") or "")
        try:
            for line in resp.iter_lines():
                now = time.perf_counter() - t0
                if now > self.session.timeout_s:
                    rec["error"] = f"no end of stream within {self.session.timeout_s:g} s"
                    break
                text = line.strip()
                if not text:
                    continue
                if rec["first_byte_s"] is None:
                    rec["first_byte_s"] = round(now, 4)
                    streaming = streaming or text.startswith(b"data:")
                if not streaming:
                    continue
                if not text.startswith(b"data:"):
                    continue
                data = text[5:].strip()
                if data == b"[DONE]":
                    break
                rec["chunks"] += 1
                try:
                    obj = json.loads(data)
                except ValueError:
                    continue
                usage = usage_fields(obj.get("usage")) if isinstance(obj, dict) else {}
                if usage.get("completion_tokens") is not None:
                    rec["completion_tokens"] = usage["completion_tokens"]
                try:
                    delta = obj["choices"][0].get("delta") or {}
                except (KeyError, IndexError, TypeError, AttributeError):
                    continue
                if rec["ttft_s"] is None and any(delta.get(k) for k in ("content", "reasoning_content", "reasoning")):
                    rec["ttft_s"] = round(now, 4)
                if rec["ttft_content_s"] is None and delta.get("content"):
                    rec["ttft_content_s"] = round(now, 4)
        except Exception as e:  # noqa: BLE001
            rec["error"] = self.redact(f"{type(e).__name__}: {e}")[:300]
        finally:
            resp.close()
        rec["total_s"] = round(time.perf_counter() - t0, 4)
        rec["stream_supported"] = streaming
        http_rec.update(usage_fields(None), finish_reason=None, stream_supported=streaming)
        self.session.log(http_rec)
        self.writer.write(rec)
        return rec


# ---------------------------------------------------------------------------------------------------------- summary
def summarize_model(model: str, cfg: dict, cases: list[dict], https: list[dict], ttfts: list[dict]) -> dict:
    final: dict[tuple, dict] = {}
    aborted_keys = set()
    for c in cases:   # the last completed record of each (case, repeat); aborted ones only count while not redone
        key = (c["case_id"], c["repeat"])
        if c["status"] == "aborted":
            aborted_keys.add(key)
        else:
            final[key] = c
    done = list(final.values())
    ok = [c for c in done if c["status"] == "ok"]
    failures: dict[str, int] = {}
    for c in done:
        if c["failure_class"]:
            failures[c["failure_class"]] = failures.get(c["failure_class"], 0) + 1
    e2e = [c["e2e_s"] for c in ok]
    e2e_nowait = [c.get("e2e_excl_wait_s") for c in ok]
    calls = [h for h in https if h.get("purpose") == "extract" and h["outcome"] == "ok"]
    call_wall = [h["wall_s"] for h in calls]
    with_ct = [h for h in calls if isinstance(h.get("completion_tokens"), int) and h["wall_s"] > 0]
    tps = [h["completion_tokens"] / h["wall_s"] for h in with_ct]
    tok = [c for c in ok if c["total_tokens"] is not None]
    cites = [(c["citations_valid"], c["facts_proposed"]) for c in ok if c["facts_proposed"]]
    gated = [c for c in ok if c["gate_decision"] in ("pass", "held")]
    decisions: dict[str, int] = {}
    for c in ok:
        decisions[str(c["gate_decision"])] = decisions.get(str(c["gate_decision"]), 0) + 1
    reasons: dict[str, int] = {}
    for c in ok:
        for r in c.get("rejection_reasons") or []:
            reasons[r] = reasons.get(r, 0) + 1
    ref = [(c["reference_matched"], c["reference_facts"]) for c in ok if c["reference_facts"]]
    by_case: dict[str, list[float]] = {}
    for c in ok:
        by_case.setdefault(c["case_id"], []).append(c["e2e_s"])
    tt = [t["ttft_s"] for t in ttfts if t.get("ttft_s") is not None]
    statuses: dict[str, int] = {}
    for h in https:
        statuses[str(h.get("status"))] = statuses.get(str(h.get("status")), 0) + 1
    success_flags = [1.0 if c["status"] == "ok" else 0.0 for c in done]
    gate_flags = [1.0 if c["gate_decision"] == "pass" else 0.0 for c in gated]
    sum_ct, sum_wall = sum(h["completion_tokens"] for h in with_ct), sum(h["wall_s"] for h in with_ct)
    streams = [t.get("stream_supported") for t in ttfts]
    return {
        "n_planned": len(cfg["case_ids"]) * cfg["repeats"], "n_completed": len(done),
        "n_aborted": len(aborted_keys - set(final)),
        "success": {"count": len(ok), "rate": rnd(len(ok) / len(done)) if done else None,
                    "ci95": bootstrap_ci(success_flags, mean, key=f"{model}:success"), "wilson95": wilson95(len(ok), len(done))},
        "failures": failures,
        "e2e_latency_s": {"n": len(e2e), "p50": rnd(median(e2e)), "p95": rnd(percentile(e2e, 95)), "mean": rnd(mean(e2e)),
                          "min": rnd(min(e2e)) if e2e else None, "max": rnd(max(e2e)) if e2e else None,
                          "p50_ci95": bootstrap_ci(e2e, median, key=f"{model}:e2e_p50"),
                          "p50_excluding_retry_waits": rnd(median(e2e_nowait))},
        "call_latency_s": {"n": len(call_wall), "p50": rnd(median(call_wall)), "p95": rnd(percentile(call_wall, 95))},
        "completion_tokens_per_s": {"n_calls": len(with_ct),
                                    "aggregate": rnd(sum_ct / sum_wall) if with_ct and sum_wall else None,
                                    "p50": rnd(median(tps))},
        "tokens_per_handover": {"n_with_usage": len(tok), "n_missing_usage": len(ok) - len(tok),
                                "mean": rnd(mean([c["total_tokens"] for c in tok]), 1),
                                "p50": rnd(median([c["total_tokens"] for c in tok]), 1),
                                "prompt_mean": rnd(mean([c["prompt_tokens"] for c in tok]), 1),
                                "completion_mean": rnd(mean([c["completion_tokens"] for c in tok]), 1)},
        "facts_per_handover": {"proposed_mean": rnd(mean([c["facts_proposed"] for c in ok]), 2),
                               "accepted_mean": rnd(mean([c["facts_accepted"] for c in ok]), 2),
                               "withheld_mean": rnd(mean([c["facts_withheld"] for c in ok]), 2),
                               "handovers_with_no_accepted_fact": sum(1 for c in ok if not c["facts_accepted"])},
        "citation_validity": {"proposed": sum(b for _, b in cites), "valid": sum(a for a, _ in cites),
                              "rate": rnd(pooled(cites)), "ci95": bootstrap_ci(cites, pooled, key=f"{model}:citations"),
                              "rejection_reasons": dict(sorted(reasons.items(), key=lambda kv: (-kv[1], kv[0])))},
        "gate": {"mode": sorted({c["gate_mode"] for c in done}) or [cfg.get("verifier_mode", "off")],
                 "decisions": decisions, "n_gated": len(gated),
                 "pass_rate": rnd(sum(gate_flags) / len(gated)) if gated else None,
                 "ci95": bootstrap_ci(gate_flags, mean, key=f"{model}:gate"),
                 "wilson95": wilson95(int(sum(gate_flags)), len(gated)) if gated else None},
        "reference_agreement_heuristic": {"recorded_facts": sum(b for _, b in ref), "matched": sum(a for a, _ in ref),
                                          "rate": rnd(pooled(ref))},
        "story_sum_of_case_p50_s": rnd(sum(median(v) for v in by_case.values()))
        if by_case and len(by_case) == len(cfg["case_ids"]) else None,
        "ttft_s": {"probes": len(ttfts), "n": len(tt), "p50": rnd(median(tt)), "p95": rnd(percentile(tt, 95)),
                   "stream_supported": True if any(s is True for s in streams) else
                   False if streams and all(s is False for s in streams) else None},
        "http": {"calls": len(https), "retries": sum(1 for h in https if h["attempt"] > 1), "statuses": statuses,
                 "calls_without_usage": sum(1 for h in calls if h.get("completion_tokens") is None)},
    }


def build_results(records: list[dict], argv_latest: list[str], stopped_reason: str | None) -> dict:
    start = next(r for r in records if r["type"] == "run_start")
    cfg = start["config"]
    invocations = [r for r in records if r["type"] == "invocation"]
    https = [r for r in records if r["type"] == "http"]
    per_model = {m: summarize_model(m, cfg, [r for r in records if r["type"] == "case" and r["model"] == m],
                                    [h for h in https if h.get("model") == m],
                                    [t for t in records if t["type"] == "ttft" and t["model"] == m]) for m in cfg["models"]}
    shas = [json.dumps(i["source_sha256"], sort_keys=True) for i in invocations]
    last = invocations[-1] if invocations else {}
    return {
        "schema_version": SCHEMA_VERSION, "created_utc": utc_now(), "git": last.get("git"), "argv": argv_latest,
        "dry_run": cfg["dry_run"],
        "endpoint": {"host": endpoint_host(cfg["base_url"]), "transport": cfg["transport"],
                     "is_token_factory_default": endpoint_host(cfg["base_url"]) == TOKEN_FACTORY_HOST},
        "pipeline": {
            "entry_point": "handoff_day1/agent/episode_events.py EpisodeJournal.add_update(update, "
                           "extractor=episode.llm_extractor(client), evidence_checker=evidence_gate.checker_from_env()), "
                           "as ui/pages/1_Family_timeline.py get_extractor() and add_verified() call it",
            "client": "llm_client.OpenAIChat.chat (production) over an instrumented HTTP layer (this script's Session)",
            "case_unit": "one story update added after the earlier updates were replayed from their recorded extraction",
            "story": cfg["story"], "story_sha256": cfg["story_sha256"], "max_tokens": cfg["max_tokens"],
            "guided_json": cfg["guided_json"], "timeout_s": cfg["timeout_s"], "max_tries": cfg["max_tries"],
            "max_wait_s": cfg["max_wait_s"], "timeout_retries": cfg["timeout_retries"],
            "backoff_base_s": cfg["backoff_base_s"], "extra_body": cfg["extra_body"],
            "verifier_mode": sorted({i.get("verifier_mode") for i in invocations}),
            "citation_check": "episode.grounding_problem: quote word for word in the update (>= 3 words, not negated), "
                              "field values and numbers from the quote, dates agree with the words",
            "gate": "evidence_gate.bind_check withhold in KINDRED_VERIFIER_MODE=gate; off in deploy/release.env.example"},
        "models": cfg["models"], "case_ids": cfg["case_ids"], "repeats": cfg["repeats"], "ttft_probe": cfg["ttft_probe"],
        "stopped_reason": stopped_reason,
        "invocations": [{"invocation": i["invocation"], "created_utc": i["created_utc"], "max_calls": i["max_calls"],
                         "git_head": (i.get("git") or {}).get("head")} for i in invocations],
        "sources_changed_between_invocations": len(set(shas)) > 1,
        "source_sha256": last.get("source_sha256"),
        "http_calls": {"total": len(https), "retries": sum(1 for h in https if h["attempt"] > 1),
                       "by_invocation": {str(i["invocation"]): sum(1 for h in https if h.get("invocation") == i["invocation"])
                                         for i in invocations}},
        "per_model": per_model,
        "statistics": {"percentile": "linear interpolation between closest ranks",
                       "bootstrap": {"resamples": BOOTSTRAP_RESAMPLES, "seed": BOOTSTRAP_SEED, "min_n": BOOTSTRAP_MIN_N,
                                     "interval": "percentile 2.5 / 97.5", "unit": "completed case"},
                       "latency_population": "successful cases only; e2e includes retries and backoff waits",
                       "tokens": "as returned in usage; null when absent, never estimated"},
    }


def validate_results(obj) -> list[str]:
    errs: list[str] = []

    def need(cond, msg):
        if not cond:
            errs.append(msg)

    def rate(x, name):
        need(x is None or (isinstance(x, (int, float)) and 0 <= x <= 1), f"{name} is not a rate or null")

    def interval(x, name):
        need(x is None or (isinstance(x, list) and len(x) == 2 and all(isinstance(v, (int, float)) for v in x)
                           and x[0] <= x[1]), f"{name} is not [low, high] or null")

    def num(x, name):
        need(x is None or (isinstance(x, (int, float)) and not isinstance(x, bool) and x >= 0), f"{name} is not >= 0 or null")

    if not isinstance(obj, dict):
        return ["results is not an object"]
    need(obj.get("schema_version") in READABLE_SCHEMA_VERSIONS, "schema_version")
    for k, t in (("created_utc", str), ("argv", list), ("dry_run", bool), ("endpoint", dict), ("pipeline", dict),
                 ("models", list), ("case_ids", list), ("repeats", int), ("per_model", dict), ("http_calls", dict),
                 ("invocations", list), ("statistics", dict)):
        need(isinstance(obj.get(k), t), f"{k} missing or not {t.__name__}")
    if errs:
        return errs
    need("://" not in obj["endpoint"].get("host", "") and "/" not in obj["endpoint"].get("host", ""), "endpoint is not host only")
    need(isinstance(obj.get("git"), dict) or obj.get("git") is None, "git")
    need(obj.get("stopped_reason") in (None, "max_calls", "interrupted"), "stopped_reason")
    need(bool(obj["models"]) and all(isinstance(m, str) for m in obj["models"]), "models")
    need(all(isinstance(a, str) for a in obj["argv"]), "argv")
    need(set(obj["per_model"]) == set(obj["models"]), "per_model keys differ from models")
    for m, s in obj["per_model"].items():
        p = f"per_model[{m}]"
        for k in ("n_planned", "n_completed", "n_aborted"):
            need(isinstance(s.get(k), int) and s[k] >= 0, f"{p}.{k}")
        need(s.get("n_completed", 0) <= s.get("n_planned", 0), f"{p}.n_completed > n_planned")
        for k in ("success", "failures", "e2e_latency_s", "call_latency_s", "completion_tokens_per_s",
                  "tokens_per_handover", "citation_validity", "gate", "ttft_s", "http"):
            need(isinstance(s.get(k), dict), f"{p}.{k}")
        if errs:
            return errs
        rate(s["success"]["rate"], f"{p}.success.rate")
        interval(s["success"]["ci95"], f"{p}.success.ci95")
        interval(s["success"]["wilson95"], f"{p}.success.wilson95")
        rate(s["citation_validity"]["rate"], f"{p}.citation_validity.rate")
        interval(s["citation_validity"]["ci95"], f"{p}.citation_validity.ci95")
        rate(s["gate"]["pass_rate"], f"{p}.gate.pass_rate")
        interval(s["gate"]["ci95"], f"{p}.gate.ci95")
        for k in ("p50", "p95", "mean", "min", "max"):
            num(s["e2e_latency_s"].get(k), f"{p}.e2e_latency_s.{k}")
        interval(s["e2e_latency_s"]["p50_ci95"], f"{p}.e2e_latency_s.p50_ci95")
        lat = s["e2e_latency_s"]
        need(lat["p50"] is None or lat["p95"] >= lat["p50"], f"{p}: p95 < p50")
        for k in ("p50", "p95"):
            num(s["call_latency_s"].get(k), f"{p}.call_latency_s.{k}")
            num(s["ttft_s"].get(k), f"{p}.ttft_s.{k}")
        num(s["completion_tokens_per_s"].get("aggregate"), f"{p}.completion_tokens_per_s.aggregate")
        num(s["tokens_per_handover"].get("mean"), f"{p}.tokens_per_handover.mean")
        need(isinstance(s["http"].get("calls"), int) and isinstance(s["http"].get("retries"), int), f"{p}.http")
        need(sum(s["failures"].values()) + s["success"]["count"] == s["n_completed"], f"{p}: failures + successes != completed")
    return errs


# ---------------------------------------------------------------------------------------------------------- reports
def fmt(x, unit="", nd=2):
    if x is None:
        return "n/a"
    if isinstance(x, float):
        return f"{x:,.{nd}f}{unit}"
    return f"{x:,}{unit}"


def fmt_ci(ci, unit="", nd=2):
    return "" if not ci else f" [{ci[0]:.{nd}f}, {ci[1]:.{nd}f}{unit}]"


def pct_s(x):
    return "n/a" if x is None else f"{100 * x:.1f}%"


def endpoint_wording(host: str, dry_run: bool) -> str:
    if dry_run:
        return ("DRY RUN: no model was called. Replies came from a scripted fake transport (agent/fake_llm_server.respond); "
                "every latency, token count and rate below exercises the harness only and is not a measurement of any "
                "model or endpoint.")
    if host == TOKEN_FACTORY_HOST:
        return (f"Inference via the AMD Token Factory endpoint provided for the AMD Developer Hackathon "
                f"(OpenAI-compatible API, host {host}). The hardware behind the endpoint is not visible to this client, "
                f"so no specific GPU is claimed. Latency includes the network path from this machine to the endpoint.")
    return (f"Inference via the OpenAI-compatible endpoint at {host} (not the AMD Token Factory default of "
            f"deploy/release.env.example). The hardware behind it is not visible to this client; no GPU is claimed.")


def summary_md(res: dict) -> str:
    host, dry = res["endpoint"]["host"], res["dry_run"]
    git = res.get("git") or {}
    lines = [f"# Handover benchmark: {', '.join('`' + m + '`' for m in res['models'])}", "", endpoint_wording(host, dry), "",
             f"- Created (UTC): {res['created_utc']}; git {str(git.get('head'))[:12]}"
             + (" (uncommitted changes in tracked files)" if git.get("dirty") else "")
             + ("" if git.get("bench_script_tracked") else "; this harness is not committed yet"),
             f"- What one case is: {res['pipeline']['case_unit']} ({res['pipeline']['story']}); the model turns that "
             "update into facts that each quote it and the grounding check accepts or rejects every quote; the evidence "
             f"verifier (KINDRED_VERIFIER_MODE {', '.join(map(str, res['pipeline']['verifier_mode']))}) holds facts for "
             "review only in gate mode.",
             f"- Entry point: {res['pipeline']['entry_point']}.",
             f"- Cases ({len(res['case_ids'])}): {', '.join(res['case_ids'])}; repeats {res['repeats']}; "
             f"settings: max_tokens {res['pipeline']['max_tokens']}, "
             f"{'guided' if res['pipeline']['guided_json'] else 'prompted'} JSON, timeout {res['pipeline']['timeout_s']:g} s, "
             f"{res['pipeline']['max_tries']} tries, extra body {json.dumps(res['pipeline']['extra_body'])}.",
             f"- HTTP calls: {res['http_calls']['total']} ({res['http_calls']['retries']} retries) over "
             f"{len(res['invocations'])} invocation(s)."
             + (f" **Stopped early: {res['stopped_reason']}; the numbers cover the completed cases only.**" if res["stopped_reason"] else "")
             + (" Source files changed between invocations." if res["sources_changed_between_invocations"] else ""), "",
             "| Model | n | Success | e2e p50 [95% CI] | e2e p95 | e2e mean | call p50 / p95 | completion tok/s | "
             "tokens / handover | citation validity [95% CI] | gate | TTFT p50 | HTTP calls | retries |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for m in res["models"]:
        s = res["per_model"][m]
        e, c, g = s["e2e_latency_s"], s["citation_validity"], s["gate"]
        gate = (pct_s(g["pass_rate"]) + fmt_ci(g["ci95"])) if g["n_gated"] else (
            "off" if set(g["decisions"]) <= {"off"} else ", ".join(f"{k} {v}" for k, v in g["decisions"].items()))
        lines.append(
            f"| `{m}` | {s['n_completed']}/{s['n_planned']} | {s['success']['count']}/{s['n_completed']} "
            f"({pct_s(s['success']['rate'])}) | {fmt(e['p50'], ' s')}{fmt_ci(e['p50_ci95'])} | {fmt(e['p95'], ' s')} | "
            f"{fmt(e['mean'], ' s')} | {fmt(s['call_latency_s']['p50'], ' s')} / {fmt(s['call_latency_s']['p95'], ' s')} | "
            f"{fmt(s['completion_tokens_per_s']['aggregate'], '', 1)} | {fmt(s['tokens_per_handover']['mean'], '', 0)} | "
            f"{pct_s(c['rate'])} ({c['valid']}/{c['proposed']}){fmt_ci(c['ci95'])} | {gate} | {fmt(s['ttft_s']['p50'], ' s')} | "
            f"{s['http']['calls']} | {s['http']['retries']} |")
    lines += ["", "## Per model", ""]
    for m in res["models"]:
        s = res["per_model"][m]
        e, t, f = s["e2e_latency_s"], s["tokens_per_handover"], s["facts_per_handover"]
        fails = ", ".join(f"{k} {v}" for k, v in s["failures"].items()) or "none"
        reasons = "; ".join(f"{v} x {k}" for k, v in list(s["citation_validity"]["rejection_reasons"].items())[:5]) or "none"
        lines += [f"### `{m}`", "",
                  f"- Success {s['success']['count']}/{s['n_completed']} (Wilson 95% {fmt_ci(s['success']['wilson95']).strip() or 'n/a'}); "
                  f"failures: {fails}; aborted (not redone): {s['n_aborted']}.",
                  f"- End to end (successful cases, n = {e['n']}): p50 {fmt(e['p50'], ' s')}, p95 {fmt(e['p95'], ' s')}, "
                  f"mean {fmt(e['mean'], ' s')}, min {fmt(e['min'], ' s')}, max {fmt(e['max'], ' s')}; p50 without retry "
                  f"waits {fmt(e['p50_excluding_retry_waits'], ' s')}. Sum of the per-case medians over the selected updates: "
                  f"{fmt(s['story_sum_of_case_p50_s'], ' s')}.",
                  f"- Tokens per handover (n = {t['n_with_usage']} with usage, {t['n_missing_usage']} without): mean "
                  f"{fmt(t['mean'], '', 0)} (prompt {fmt(t['prompt_mean'], '', 0)}, completion {fmt(t['completion_mean'], '', 0)}), "
                  f"p50 {fmt(t['p50'], '', 0)}. Completion tokens per second of call wall time: aggregate "
                  f"{fmt(s['completion_tokens_per_s']['aggregate'], '', 1)}, per-call p50 {fmt(s['completion_tokens_per_s']['p50'], '', 1)} "
                  "(includes prompt processing and the network: not a decode speed).",
                  f"- Facts per handover: {fmt(f['proposed_mean'])} proposed, {fmt(f['accepted_mean'])} accepted, "
                  f"{fmt(f['withheld_mean'])} withheld by the gate; {f['handovers_with_no_accepted_fact']} handover(s) with no "
                  f"accepted fact. Grounding rejections: {reasons}.",
                  f"- Agreement with the story's recorded extraction (heuristic: same type, overlapping quote; not a quality "
                  f"score): {s['reference_agreement_heuristic']['matched']}/{s['reference_agreement_heuristic']['recorded_facts']} "
                  f"({pct_s(s['reference_agreement_heuristic']['rate'])}).",
                  f"- TTFT ({s['ttft_s']['probes']} streaming probes, fixed short prompt): p50 {fmt(s['ttft_s']['p50'], ' s')}, "
                  f"p95 {fmt(s['ttft_s']['p95'], ' s')}; streaming supported: {s['ttft_s']['stream_supported']}.",
                  f"- HTTP statuses: {', '.join(f'{k}: {v}' for k, v in s['http']['statuses'].items()) or 'none'}.", ""]
    if not dry:
        lines += ["## Wording for the write-up", ""]
        for m in res["models"]:
            s = res["per_model"][m]
            e, t, c = s["e2e_latency_s"], s["tokens_per_handover"], s["citation_validity"]
            if e["p50"] is None:
                lines.append(f"- `{m}`: no successful handover in this run; no claim.")
                continue
            ci = e["p50_ci95"]
            ci_text = f", 95% CI of the median {ci[0]:.1f} to {ci[1]:.1f} s" if ci else ""
            tokens = (f"at a mean of {t['mean']:,.0f} tokens (prompt + completion, as reported by the endpoint), "
                      if t["mean"] is not None else "(the endpoint reported no token usage), ")
            lines.append(
                f"- `{m}`: one caregiver update was turned into sourced facts and a timeline entry in a median of "
                f"{e['p50']:.1f} s (p95 {e['p95']:.1f} s{ci_text}) " + tokens
                + f"n = {e['n']}, {s['success']['count']}/{s['n_completed']} successful; {pct_s(c['rate'])} of proposed "
                f"quotes passed the grounding check. " + endpoint_wording(host, dry).split(". ")[0] + ".")
        lines.append("")
    lines += ["Notes: latency covers successful cases and includes retries and backoff waits; tokens are the endpoint's "
              "`usage` (n/a where it sent none, never estimated); bootstrap intervals resample completed cases "
              f"({BOOTSTRAP_RESAMPLES} resamples, seed {BOOTSTRAP_SEED}, none below n = {BOOTSTRAP_MIN_N}); a rate of 100% gives a "
              "bootstrap interval of [1, 1], so the Wilson interval is listed with it. The story is the fictional demo "
              "episode; the numbers are engineering measurements, not clinical validation.", ""]
    return "\n".join(lines)


def latency_svg(res: dict, records: list[dict]) -> str:
    models = res["models"]
    row_h, top, left, right_x = 64, 70, 190, 700
    width, height = 980, top + row_h * len(models) + 60
    lat = {m: sorted(r["e2e_s"] for r in records if r.get("type") == "case" and r["model"] == m and r["status"] == "ok")
           for m in models}
    vmax = max([v for xs in lat.values() for v in xs] + [0.0])
    step = 10 ** math.floor(math.log10(vmax)) if vmax > 0 else 0.1
    xmax = math.ceil(vmax / step) * step if vmax > 0 else 1.0
    if xmax / step > 8:
        step *= 2
    x = (lambda v: left + (v / xmax) * (right_x - 60 - left))
    tps = {m: res["per_model"][m]["completion_tokens_per_s"]["aggregate"] for m in models}
    tmax = max([v for v in tps.values() if v] + [1.0])
    bar0, bar_w = right_x + 40, width - right_x - 110
    title = "Handover end-to-end latency (successful cases) and completion tokens per second"
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
           'font-family="Helvetica, Arial, sans-serif" font-size="12">',
           f'<rect width="{width}" height="{height}" fill="white"/>',
           f'<text x="20" y="24" font-size="15" font-weight="bold">{xml_escape(title)}</text>',
           f'<text x="20" y="44" fill="#555">{xml_escape(("DRY RUN, fake transport: not a measurement. " if res["dry_run"] else "")
                                                     + "Endpoint " + res["endpoint"]["host"] + "; dots = cases, box = p25 to p75, bar = p50, tick = p95")}</text>']
    axis_y = top + row_h * len(models)
    ticks, v = [], 0.0
    while v <= xmax + 1e-9:
        ticks.append(v)
        v += step
    for t in ticks:
        out.append(f'<line x1="{x(t):.1f}" y1="{top - 10}" x2="{x(t):.1f}" y2="{axis_y}" stroke="#eee"/>')
        out.append(f'<text x="{x(t):.1f}" y="{axis_y + 16}" text-anchor="middle" fill="#555">{t:g}</text>')
    out.append(f'<text x="{(left + right_x - 60) / 2:.1f}" y="{axis_y + 34}" text-anchor="middle">seconds</text>')
    out.append(f'<text x="{bar0}" y="{top - 16}" fill="#555">completion tokens / s (aggregate)</text>')
    for i, m in enumerate(models):
        cy = top + row_h * i + row_h / 2
        xs = lat[m]
        out.append(f'<text x="{left - 12}" y="{cy + 4:.1f}" text-anchor="end">{xml_escape(m)}</text>')
        if xs:
            q1, q2, q3, q95 = (percentile(xs, q) for q in (25, 50, 75, 95))
            out.append(f'<rect x="{x(q1):.1f}" y="{cy - 12:.1f}" width="{max(1.0, x(q3) - x(q1)):.1f}" height="24" '
                       'fill="#dbe8f6" stroke="#4a78b0"/>')
            out.append(f'<line x1="{x(q2):.1f}" y1="{cy - 14:.1f}" x2="{x(q2):.1f}" y2="{cy + 14:.1f}" stroke="#1f3f6b" stroke-width="3"/>')
            out.append(f'<line x1="{x(q95):.1f}" y1="{cy - 8:.1f}" x2="{x(q95):.1f}" y2="{cy + 8:.1f}" stroke="#b04a4a" stroke-width="2"/>')
            for j, val in enumerate(xs):
                out.append(f'<circle cx="{x(val):.1f}" cy="{cy - 6 + (j % 5) * 3:.1f}" r="2.5" fill="#333" fill-opacity="0.6"/>')
            out.append(f'<text x="{min(x(q95) + 8, right_x - 20):.1f}" y="{cy + 22:.1f}" fill="#555">p50 {q2:.2f} s, '
                       f'p95 {q95:.2f} s, n {len(xs)}</text>')
        else:
            out.append(f'<text x="{left}" y="{cy + 4:.1f}" fill="#b04a4a">no successful case</text>')
        tv = tps[m]
        if tv:
            out.append(f'<rect x="{bar0}" y="{cy - 10:.1f}" width="{max(1.0, bar_w * tv / tmax):.1f}" height="20" fill="#7aa874"/>')
            out.append(f'<text x="{bar0 + max(1.0, bar_w * tv / tmax) + 6:.1f}" y="{cy + 4:.1f}">{tv:.1f}</text>')
        else:
            out.append(f'<text x="{bar0}" y="{cy + 4:.1f}" fill="#555">n/a (no usage)</text>')
    out.append(f'<line x1="{left}" y1="{axis_y}" x2="{right_x - 60}" y2="{axis_y}" stroke="#333"/>')
    out.append("</svg>")
    return "\n".join(out) + "\n"


def write_outputs(out: Path, redact: Redactor, argv: list[str], stopped_reason: str | None) -> dict:
    skipped: list[int] = []
    records = read_records(out / "records.jsonl", skipped)
    for i, rec in enumerate(records):
        errs = validate_record(rec)
        if errs:
            raise ValueError(f"records.jsonl record {i + 1}: {'; '.join(errs)}")
    res = build_results(records, argv, stopped_reason)
    res["records_skipped_lines"] = skipped   # interrupted writes, left out of every number
    errs = validate_results(res)
    if errs:
        raise ValueError("results.json would not be valid: " + "; ".join(errs))
    for name, text in (("results.json", json.dumps(res, indent=2, ensure_ascii=False) + "\n"),
                       ("summary.md", summary_md(res)), ("latency.svg", latency_svg(res, records))):
        (out / name).write_text(redact(text), encoding="utf-8")
    scrub_outputs(out, redact)
    return res


def scrub_outputs(out: Path, redact: Redactor) -> int:
    """Belt and braces: rewrite any output file in which the redactor still finds something. Returns files rewritten."""
    n = 0
    for p in sorted(out.iterdir()):
        if p.is_file():
            text = p.read_text(encoding="utf-8", errors="replace")
            clean = redact(text)
            if clean != text:
                p.write_text(clean, encoding="utf-8")
                n += 1
    return n


# ---------------------------------------------------------------------------------------------------------- CLI
def git_info() -> dict:
    def git(*args):
        try:
            r = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            return None
        return r if r.returncode in (0, 1) else None
    head = git("rev-parse", "HEAD")
    status = git("status", "--porcelain")
    tracked = git("ls-files", "--error-unmatch", "scripts/bench_tf_handover.py")
    lines = status.stdout.splitlines() if status and status.returncode == 0 else None
    return {"head": head.stdout.strip() if head and head.returncode == 0 else None,
            "dirty": None if lines is None else any(not ln.startswith("??") for ln in lines),
            "untracked_files": None if lines is None else sum(ln.startswith("??") for ln in lines),
            "bench_script_tracked": None if tracked is None else tracked.returncode == 0}


def file_sha(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def rel(path: Path) -> str:
    p = Path(path).resolve()
    try:
        return p.relative_to(ROOT).as_posix()
    except ValueError:
        return p.as_posix()


def parse_args(argv):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--models", default=None, help="comma-separated model ids (default: CARERELAY_LLM_MODEL, else the "
                                                   "release model of deploy/release.env.example)")
    ap.add_argument("--cases", type=int, default=None, help="the story's first N updates (default: all)")
    ap.add_argument("--repeats", type=int, default=None, help="runs of each case per model (default 1)")
    ap.add_argument("--out", default=None, help="new output folder (must not exist)")
    ap.add_argument("--resume", default=None, metavar="DIR", help="continue the run in DIR, skipping completed cases")
    ap.add_argument("--base-url", default=None, help="OpenAI-compatible base URL ending in /v1 (default: "
                                                     "CARERELAY_LLM_BASE_URL, else deploy/release.env.example)")
    ap.add_argument("--api-key-file", default=None, help="file holding only the API key (else CARERELAY_LLM_API_KEY)")
    ap.add_argument("--list-models", action="store_true", help="GET /models and print the model ids")
    ap.add_argument("--dry-run", action="store_true", help="no network: a deterministic scripted fake endpoint")
    ap.add_argument("--max-calls", type=int, default=400, help="hard cap on HTTP calls in this invocation (default 400)")
    ap.add_argument("--ttft-probe", type=int, default=None, metavar="K", help="K streaming requests per model to measure "
                                                                             "time to first token (default 0)")
    ap.add_argument("--story", default=None, help="episode story JSON (default: CARERELAY_STORY, else the demo story)")
    ap.add_argument("--max-tries", type=int, default=None, help="tries per request (default CARERELAY_LLM_MAX_TRIES or 6)")
    ap.add_argument("--max-wait-s", type=float, default=None, help="cap of one backoff wait (default "
                                                                   "CARERELAY_LLM_MAX_WAIT_S or 60)")
    ap.add_argument("--timeout-s", type=float, default=None, help="per-attempt timeout (default CARERELAY_LLM_TIMEOUT_S, "
                                                                  "else deploy/release.env.example, else 180)")
    return ap.parse_args(argv)


def env_num(env, name, default):
    try:
        return float(env.get(name) or default)
    except ValueError:
        return float(default)


def new_config(args, env, defaults, transport_name: str) -> dict:
    models = list(dict.fromkeys(m.strip() for m in (args.models or env.get("CARERELAY_LLM_MODEL")
                                                    or defaults.get("CARERELAY_LLM_MODEL") or FALLBACK_MODEL).split(",") if m.strip()))
    if not models:
        raise UsageError("--models names no model")
    repeats = 1 if args.repeats is None else args.repeats
    ttft = 0 if args.ttft_probe is None else args.ttft_probe
    if repeats < 1 or ttft < 0 or args.max_calls < 1:
        raise UsageError("--repeats and --max-calls must be at least 1, --ttft-probe at least 0")
    story = Path(args.story or env.get("CARERELAY_STORY") or DEFAULT_STORY)
    if not story.is_absolute():
        story = (Path.cwd() / story).resolve()
    if not story.is_file():
        raise UsageError(f"story not found: {story}")
    scenario = load_scenario(story)
    cases = select_cases(scenario, story.stem, args.cases)
    guided = (env.get("CARERELAY_LLM_GUIDED_JSON") or defaults.get("CARERELAY_LLM_GUIDED_JSON") or "1").strip() != "0"
    try:
        extra = json.loads(env.get("CARERELAY_LLM_EXTRA_BODY") or "{}")
    except ValueError:
        raise UsageError("CARERELAY_LLM_EXTRA_BODY is not JSON") from None

    def credential_like(v):
        return isinstance(v, dict) and any(CREDENTIAL_KEY.search(str(k)) or credential_like(x) for k, x in v.items())
    if not isinstance(extra, dict) or credential_like(extra):
        raise UsageError("CARERELAY_LLM_EXTRA_BODY must be a JSON object without credential-like fields")
    return {"models": models, "case_ids": [c["case_id"] for c in cases], "repeats": repeats, "ttft_probe": ttft,
            "max_calls": args.max_calls, "dry_run": bool(args.dry_run), "transport": transport_name,
            "base_url": check_base_url(args.base_url or env.get("CARERELAY_LLM_BASE_URL")
                                       or defaults.get("CARERELAY_LLM_BASE_URL") or FALLBACK_BASE_URL),
            "story": rel(story), "story_sha256": file_sha(story), "max_tokens": PAGE_MAX_TOKENS, "guided_json": guided,
            "timeout_s": args.timeout_s or max(1.0, env_num(env, "CARERELAY_LLM_TIMEOUT_S",
                                                            defaults.get("CARERELAY_LLM_TIMEOUT_S") or 180)),
            "max_tries": args.max_tries or int(env_num(env, "CARERELAY_LLM_MAX_TRIES", 6)),
            "max_wait_s": args.max_wait_s if args.max_wait_s is not None else env_num(env, "CARERELAY_LLM_MAX_WAIT_S", 60),
            "timeout_retries": int(env_num(env, "CARERELAY_LLM_TIMEOUT_RETRIES", 0)), "backoff_base_s": BACKOFF_BASE_S,
            "extra_body": extra}


def resumed_config(args, out: Path) -> tuple[dict, int]:
    path = out / "records.jsonl"
    if not path.is_file():
        raise UsageError(f"--resume: {path} not found")
    records = read_records(path)
    start = next((r for r in records if r.get("type") == "run_start"), None)
    if start is None or start.get("schema_version") != SCHEMA_VERSION:   # a v1 run's case records lack rejected_facts
        raise UsageError(f"--resume: {path} was not written by this benchmark version; start a new --out")
    cfg = dict(start["config"])
    given = {"models": args.models and list(dict.fromkeys(m.strip() for m in args.models.split(",") if m.strip())),
             "repeats": args.repeats, "ttft_probe": args.ttft_probe,
             "base_url": args.base_url and check_base_url(args.base_url)}
    for k, v in given.items():
        if v not in (None, []) and v != cfg[k]:
            raise UsageError(f"--resume: --{k.replace('_', '-')} differs from the run being resumed; start a new --out")
    if args.cases is not None and args.cases != len(cfg["case_ids"]):
        raise UsageError("--resume: --cases differs from the run being resumed; start a new --out")
    if bool(args.dry_run) != cfg["dry_run"]:
        raise UsageError("--resume: a dry run and a live run cannot be mixed; " +
                         ("add --dry-run" if cfg["dry_run"] else "drop --dry-run"))
    if file_sha(ROOT / cfg["story"]) != cfg["story_sha256"]:
        raise UsageError("--resume: the story file changed since the run started; start a new --out")
    cfg["max_calls"] = args.max_calls
    invocation = 1 + max((r["invocation"] for r in records if r.get("type") == "invocation"), default=0)
    return cfg, invocation


def main(argv=None, *, transport=None, sleep=time.sleep, checker="env", env=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    env = os.environ if env is None else env
    stdout, stderr = sys.stdout, sys.stderr
    redact = Redactor(None)
    try:
        args = parse_args(argv)
        key = load_api_key(args.api_key_file, env)
        redact = Redactor(key)
        sys.stdout, sys.stderr = RedactingStream(stdout, redact), RedactingStream(stderr, redact)
        if not args.dry_run and not key:
            raise UsageError("no API key: pass --api-key-file FILE (only the key in it) or set CARERELAY_LLM_API_KEY")
        defaults = release_defaults()
        if args.list_models:
            base = check_base_url(args.base_url or env.get("CARERELAY_LLM_BASE_URL")
                                  or defaults.get("CARERELAY_LLM_BASE_URL") or FALLBACK_BASE_URL)
            models = [m.strip() for m in (args.models or "").split(",") if m.strip()] or ["fake-model"]
            tr = transport or (FakeTransport(models) if args.dry_run else UrllibTransport())
            sess = Session(base, key, tr, CallBudget(args.max_calls), timeout_s=args.timeout_s or 60.0,
                           max_tries=args.max_tries or 3, max_wait_s=args.max_wait_s if args.max_wait_s is not None else 30.0,
                           sleep=sleep, redact=redact)
            try:
                resp, rec = sess.send("GET", "/models")
                data = json.loads(resp.body)
            except Exception as e:  # noqa: BLE001
                print(f"cannot list models at {endpoint_host(base)}: {redact(f'{type(e).__name__}: {e}')[:300]}", file=sys.stderr)
                return EXIT_USAGE
            for m in (data.get("data") or []) if isinstance(data, dict) else []:
                if isinstance(m, dict) and m.get("id"):
                    print(m["id"])
            return EXIT_OK
        if bool(args.out) == bool(args.resume):
            raise UsageError("give exactly one of --out DIR (a new run) or --resume DIR")
        if args.out:
            out = Path(args.out)
            if out.exists():
                raise UsageError(f"--out {out} already exists; choose a new folder (or --resume it)")
            cfg = new_config(args, env, defaults, "fake" if args.dry_run else "urllib")
            invocation = 1
        else:
            out = Path(args.resume)
            cfg, invocation = resumed_config(args, out)
        tr = transport or (FakeTransport(cfg["models"]) if cfg["dry_run"] else UrllibTransport())
        cfg["transport"] = getattr(tr, "name", type(tr).__name__)
        verifier_mode = "off" if checker is None else (env.get("KINDRED_VERIFIER_MODE", "off").lower() if checker == "env"
                                                      else str(getattr(checker, "mode", "gate")))
        try:
            if checker == "env":
                checker = checker_from_env()
        except ValueError as e:
            raise UsageError(f"evidence verifier settings: {e}") from None
        if args.out:
            out.mkdir(parents=True)
        writer = RecordWriter(out / "records.jsonl", redact)
        if invocation == 1:
            writer.write({"type": "run_start", "ts": utc_now(), "schema_version": SCHEMA_VERSION, "invocation": 1,
                          "config": {k: v for k, v in cfg.items() if k != "max_calls"}})
        writer.write({"type": "invocation", "ts": utc_now(), "invocation": invocation, "argv": stored_argv(argv, redact),
                      "created_utc": utc_now(), "git": git_info(),
                      "source_sha256": {s: file_sha(ROOT / s) for s in SOURCES}, "max_calls": cfg["max_calls"],
                      "verifier_mode": verifier_mode, "python": sys.version.split()[0]})
        print(endpoint_wording(endpoint_host(cfg["base_url"]), cfg["dry_run"]).split(". ")[0] + ".")
        try:
            bench = Bench(cfg, out, transport=tr, api_key=key, invocation=invocation, sleep=sleep, checker=checker)
        except json.JSONDecodeError:   # OpenAIChat reads CARERELAY_LLM_EXTRA_BODY itself before the run's value is set
            raise UsageError("CARERELAY_LLM_EXTRA_BODY is not JSON") from None
        stopped, code = None, EXIT_OK
        try:
            stopped = bench.run()
            code = EXIT_PARTIAL if stopped else EXIT_OK
        except KeyboardInterrupt:
            stopped, code = "interrupted", EXIT_INTERRUPTED
            print(f"interrupted; continue with --resume {out}")
        writer.write({"type": "invocation_end", "ts": utc_now(), "invocation": invocation, "stopped_reason": stopped,
                      "http_calls": bench.budget.used})
        res = write_outputs(out, redact, stored_argv(argv, redact), stopped)
        for m in res["models"]:
            s = res["per_model"][m]
            print(f"{m}: {s['success']['count']}/{s['n_completed']} ok, e2e p50 {fmt(s['e2e_latency_s']['p50'], ' s')}, "
                  f"p95 {fmt(s['e2e_latency_s']['p95'], ' s')}, tokens/handover {fmt(s['tokens_per_handover']['mean'], '', 0)}, "
                  f"citation validity {pct_s(s['citation_validity']['rate'])}")
        print(f"wrote {out / 'records.jsonl'}, results.json, summary.md, latency.svg")
        return code
    except UsageError as e:
        print(f"bench_tf_handover: {redact(str(e))}", file=sys.stderr)
        return EXIT_USAGE
    finally:
        sys.stdout, sys.stderr = stdout, stderr


if __name__ == "__main__":
    sys.exit(main())
