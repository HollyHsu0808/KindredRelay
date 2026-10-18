"""LLM access for the CareRelay Case Agent.

One interface, two backends:
  OpenAIChat        any OpenAI-compatible server: vLLM on a Kaggle GPU now, vLLM on the AMD MI300X later.
                    Only the base URL and model name change (CARERELAY_LLM_BASE_URL / CARERELAY_LLM_MODEL).
  TransformersChat  in-process Hugging Face transformers, as a fallback when vLLM cannot be installed.
Both return the same dict: text, parsed JSON (or None), latency, token usage and how JSON was obtained.

Structured output: OpenAIChat first asks the server for JSON-schema guided decoding (vLLM supports
response_format json_schema); if the server rejects it, it falls back to plain prompting plus JSON extraction (said
once on stderr). CARERELAY_LLM_GUIDED_JSON=0 starts with prompted JSON, for a server whose rejection is not recognised.
A server that rejects chat_template_kwargs (CARERELAY_LLM_EXTRA_BODY) gets a clear error that names the remedy.

Hosted endpoints: HTTP 429, transient 5xx and reset connections are retried with backoff (2, 4, 8, ... s, or the
server's Retry-After), at most CARERELAY_LLM_MAX_TRIES tries (default 6) and CARERELAY_LLM_MAX_WAIT_S seconds per wait
(default 60). A reply that does not come within CARERELAY_LLM_TIMEOUT_S (default 180) is not retried, because the
server may still be working on it, unless CARERELAY_LLM_TIMEOUT_RETRIES allows it (default 0; scripts/amd_llm_run.sh
sets 1 and a 400 s timeout for a hosted endpoint). Each wait is one line on stderr and, when CARERELAY_LLM_RETRY_LOG
names a file, one JSON line there (scripts/amd_llm_run.sh counts them in its summary). latency_s is the round trip of
the try that succeeded: failed tries and the waits between tries are left out (each failed try's duration is in the
retry log as attempt_s).
Opt-in call trace (the app shell's AMD Runtime view): a CallRecorder made active with start_call_recording() is bound to
every OpenAIChat created while it is active, in that thread / context, and gets one row per chat request: model, endpoint
host, latency, token usage as the server reported it (None when absent, never estimated), outcome, and a SHA-256 of the
reply text. Never the prompt, the reply, an image, the API key or the URL beyond its host. With no recorder active
(the default) nothing is recorded and chat() behaves as before.
Stdlib only for OpenAIChat.
"""
from __future__ import annotations

import collections
import contextvars
import datetime as dt
import email.utils
import hashlib
import http.client
import json
import os
import re
import socket
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_BASE_URL = "http://127.0.0.1:8000/v1"


class CallRecorder:
    """A bounded, thread-safe record of chat requests for a runtime panel: the newest maxlen rows are kept, the oldest
    dropped. Holds only the metadata OpenAIChat._trace writes (see the module docstring)."""

    def __init__(self, maxlen: int = 100):
        self._rows: collections.deque = collections.deque(maxlen=max(1, int(maxlen)))
        self._lock = threading.Lock()
        self._seq = 0

    def record(self, row: dict) -> None:
        with self._lock:
            self._seq += 1
            self._rows.append({**row, "seq": self._seq})

    def calls(self) -> list[dict]:
        """Copies of the kept rows, oldest first."""
        with self._lock:
            return [dict(r) for r in self._rows]

    @property
    def total(self) -> int:
        """Rows recorded since creation, including those the bound has dropped."""
        with self._lock:
            return self._seq

    def clear(self) -> None:
        with self._lock:
            self._rows.clear()


_CALL_RECORDER: contextvars.ContextVar = contextvars.ContextVar("carerelay_llm_call_recorder", default=None)


def start_call_recording(recorder: CallRecorder | None) -> contextvars.Token:
    """Bind `recorder` to every OpenAIChat created from now on in this thread / context; the token undoes it
    (stop_call_recording). Clients created earlier keep the recorder they were created with (or none)."""
    return _CALL_RECORDER.set(recorder)


def stop_call_recording(token: contextvars.Token) -> None:
    _CALL_RECORDER.reset(token)


def _env_num(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name) or default)
    except ValueError:
        return default


def retry_after_s(value: str | None) -> float | None:
    """A Retry-After header in seconds: a number of seconds or an HTTP date. None when absent or unreadable."""
    v = (value or "").strip()
    if not v:
        return None
    try:
        return max(0.0, float(v))
    except ValueError:
        pass
    try:
        when = email.utils.parsedate_to_datetime(v)
    except (TypeError, ValueError, IndexError):
        return None
    if when is None:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=dt.timezone.utc)
    return max(0.0, (when - dt.datetime.now(dt.timezone.utc)).total_seconds())


def retry_reason(exc: BaseException) -> str | None:
    """Why a failed request is worth another try (HTTP 429, a transient 5xx, a reset connection), else None.
    501 / 505 and every other 4xx are answers, not hiccups; a timeout is not retried here (the server may still be
    working): urlopen_retrying retries it only as often as CARERELAY_LLM_TIMEOUT_RETRIES allows."""
    if isinstance(exc, urllib.error.HTTPError):
        if exc.code == 429:
            return "HTTP 429"
        return f"HTTP {exc.code}" if 500 <= exc.code <= 599 and exc.code not in (501, 505) else None
    if isinstance(exc, urllib.error.URLError):
        exc = exc.reason if isinstance(exc.reason, BaseException) else exc
    if isinstance(exc, (ConnectionResetError, ConnectionAbortedError, BrokenPipeError, http.client.RemoteDisconnected,
                        http.client.IncompleteRead)):
        return "connection reset"
    return None


def is_timeout(exc: BaseException) -> bool:
    """No reply within the client's timeout (raised as TimeoutError, or wrapped in a URLError while connecting).
    socket.timeout is TimeoutError only from Python 3.10 on; the scripts accept 3.9."""
    if isinstance(exc, urllib.error.URLError) and isinstance(exc.reason, BaseException):
        exc = exc.reason
    return isinstance(exc, (TimeoutError, socket.timeout))


def _log_retry(row: dict) -> None:
    path = os.environ.get("CARERELAY_LLM_RETRY_LOG")
    if not path:
        return
    row = {"t": round(time.time(), 3), "utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), **row}
    try:
        with open(path, "a") as f:
            f.write(json.dumps(row) + "\n")
    except OSError:
        pass


def urlopen_retrying(req: urllib.request.Request, timeout: float, what: str = "request", max_tries: int | None = None,
                     max_wait: float | None = None) -> tuple[bytes, float, float]:
    """(response body, seconds spent waiting between tries, seconds the successful try took). Retries what
    retry_reason() accepts, honouring Retry-After; the last failure is raised as it came (an HTTPError keeps its body
    unread for the caller). max_tries / max_wait: this caller's limits (default: the environment's), e.g. a family
    member waiting on the page gets a short budget, then the deterministic answer."""
    max_tries = max(1, int(max_tries if max_tries is not None else _env_num("CARERELAY_LLM_MAX_TRIES", 6)))
    max_wait = max(0.0, max_wait if max_wait is not None else _env_num("CARERELAY_LLM_MAX_WAIT_S", 60.0))
    timeout_retries = max(0, int(_env_num("CARERELAY_LLM_TIMEOUT_RETRIES", 0)))
    waited, timeouts = 0.0, 0
    for attempt in range(1, max_tries + 1):
        a0 = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                # the socket timeout only bounds each wait for bytes: a server that trickles its reply could keep one
                # try going for ever, so a try whose reply is still arriving after the same number of seconds is cut off
                chunks, read = [], getattr(r, "read1", r.read)
                while chunk := read(65536):
                    chunks.append(chunk)
                    if time.perf_counter() - a0 > timeout and not r.isclosed():   # closed: the last byte is in
                        raise TimeoutError(f"the reply was still arriving after {timeout:g} s")
                if getattr(r, "length", None):   # read1 ends quietly when a Content-Length body is cut short
                    raise http.client.IncompleteRead(b"".join(chunks), r.length)
                body = b"".join(chunks)
            return body, waited, time.perf_counter() - a0
        except Exception as e:  # noqa: BLE001 - only retry_reason() cases are retried, the rest is re-raised
            attempt_s = round(time.perf_counter() - a0, 3)
            reason = retry_reason(e)
            if reason is None and is_timeout(e):
                timeouts += 1
                if timeouts > timeout_retries or attempt == max_tries:
                    print(f"[llm_client] no reply within {timeout:g} s on {what}: giving up after {timeouts} timeout(s)",
                          file=sys.stderr, flush=True)
                    _log_retry({"what": what, "reason": "timeout", "status": None, "try": attempt, "max_tries": max_tries,
                                "attempt_s": attempt_s, "timeout_s": timeout, "gave_up": True})
                    raise
                reason = "timeout"
            if reason is None:
                raise
            status = e.code if isinstance(e, urllib.error.HTTPError) else None
            ra_raw = e.headers.get("Retry-After") if isinstance(e, urllib.error.HTTPError) and e.headers else None
            if attempt == max_tries:
                print(f"[llm_client] {reason} on {what}: giving up after {max_tries} tries", file=sys.stderr, flush=True)
                _log_retry({"what": what, "reason": reason, "status": status, "try": attempt, "max_tries": max_tries,
                            "attempt_s": attempt_s, "gave_up": True})
                raise
            if isinstance(e, urllib.error.HTTPError):
                try:
                    e.close()   # the body of a 429 / 5xx is not needed: free the connection
                except Exception:  # noqa: BLE001
                    pass
            ra = retry_after_s(ra_raw)
            honoured, capped = ra is not None and ra <= max_wait, ra is not None and ra > max_wait
            wait = min(ra if ra is not None else 2.0 * 2 ** (attempt - 1), max_wait)
            if ra is not None:
                how = f"Retry-After {ra_raw.strip()[:40]}" + (f", capped at {max_wait:g} s" if capped else "")
            elif ra_raw and ra_raw.strip():
                how = f"backoff; Retry-After {ra_raw.strip()[:40]!r} unreadable"
            else:
                how = "backoff"
            print(f"[llm_client] {reason} on {what}: waiting {wait:.1f} s ({how}) before try {attempt + 1} of {max_tries}",
                  file=sys.stderr, flush=True)
            # retry_after = the raw header; honoured = the wait followed it; capped = it asked for more than max_wait
            _log_retry({"what": what, "reason": reason, "status": status,
                        "retry_after": ra_raw.strip()[:40] if ra_raw else None,
                        "retry_after_s": None if ra is None else round(ra, 3), "honoured": honoured, "capped": capped,
                        "wait_s": round(wait, 3), "attempt_s": attempt_s, "try": attempt, "max_tries": max_tries})
            time.sleep(wait)
            waited += wait
    raise AssertionError("unreachable")


def extract_json(text: str):
    """First JSON object in a model reply (handles ```json fences and leading prose). None if there is none."""
    if not text:
        return None
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    candidates = [fence.group(1)] if fence else []
    start = text.find("{")
    while start != -1:  # try every opening brace: an invalid {...} (e.g. inside prose) must not hide a valid object later
        depth, in_str, esc = 0, False, False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                esc = (ch == "\\") and not esc
                if ch == '"' and not esc:
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidates.append(text[start:i + 1])
                    break
        start = text.find("{", start + 1)
    for c in candidates:
        try:
            obj = json.loads(c)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            return obj
    return None


def strip_thinking(text: str) -> str:
    """Remove reasoning text: everything up to the last </think> (templates may add the opening tag themselves);
    an unclosed <think> (cut off at max_tokens) drops the rest."""
    if "</think>" in text:
        text = text.rsplit("</think>", 1)[1]
    elif "<think>" in text:
        text = text.split("<think>", 1)[0]
    return text.strip()


def _schema_hint(schema: dict) -> str:
    return ("Respond with ONE JSON object only, no prose before or after, matching this JSON Schema:\n"
            + json.dumps(schema, ensure_ascii=False))


class OpenAIChat:
    """Client for an OpenAI-compatible /chat/completions endpoint (vLLM, llama.cpp server, etc.)."""

    def __init__(self, base_url: str | None = None, model: str | None = None, api_key: str | None = None,
                 timeout_s: float | None = None, temperature: float = 0.0, max_tokens: int = 700, seed: int | None = 0,
                 max_tries: int | None = None, max_wait_s: float | None = None):
        self.max_tries, self.max_wait_s = max_tries, max_wait_s   # None: CARERELAY_LLM_MAX_TRIES / _MAX_WAIT_S
        self.base_url = (base_url or os.environ.get("CARERELAY_LLM_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        self.api_key = api_key or os.environ.get("CARERELAY_LLM_API_KEY") or "EMPTY"
        self.timeout_s = timeout_s or max(1.0, _env_num("CARERELAY_LLM_TIMEOUT_S", 180.0))
        self.temperature, self.max_tokens, self.seed = temperature, max_tokens, seed
        self.model = model or os.environ.get("CARERELAY_LLM_MODEL") or self._first_model()
        # flipped off after the first rejection; CARERELAY_LLM_GUIDED_JSON=0 starts with prompted JSON
        self.guided_json_supported = (os.environ.get("CARERELAY_LLM_GUIDED_JSON") or "1").strip() != "0"
        # extra request fields, e.g. '{"chat_template_kwargs": {"enable_thinking": false}}' for Qwen3-style thinking models
        self.extra_body = json.loads(os.environ.get("CARERELAY_LLM_EXTRA_BODY") or "{}")
        self.last_wait_s = 0.0  # seconds the last request spent waiting between retries
        self.last_attempt_s = 0.0  # seconds the last request's successful try took (latency_s)
        self.recorder = _CALL_RECORDER.get()  # opt-in call trace bound at creation; None (the default): nothing recorded

    def _trace(self, started: float, messages: list, json_schema: dict | None, schema_name: str, mode: str,
               out=None, text: str | None = None, error: str | None = None) -> None:
        """One row for the opt-in call recorder; without one, nothing happens. Metadata only (module docstring). A
        recorder problem never fails the call: the trace is diagnostics."""
        recorder = getattr(self, "recorder", None)
        if recorder is None:
            return
        try:
            usage = out.get("usage") if isinstance(out, dict) else None
            usage = usage if isinstance(usage, dict) else {}

            def count(key):   # as the server reported it; anything else is None, never an estimate
                v = usage.get(key)
                return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else None
            images = sum(1 for m in messages if isinstance(m, dict) and isinstance(m.get("content"), list)
                         for p in m["content"] if isinstance(p, dict) and p.get("type") == "image_url")
            served = out.get("model") if isinstance(out, dict) else None
            ok = error is None
            recorder.record({
                "utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                "backend": "openai_compatible", "model": self.model, "served_model": served if isinstance(served, str) else None,
                "host": urllib.parse.urlsplit(self.base_url).hostname,
                "schema": schema_name if json_schema is not None else None, "images": images, "json_mode": mode,
                "ok": ok, "error": error,
                "latency_s": round(self.last_attempt_s, 3) if ok else None, "wait_s": round(self.last_wait_s, 3) if ok else None,
                "elapsed_s": round(time.perf_counter() - started, 3),
                "prompt_tokens": count("prompt_tokens"), "completion_tokens": count("completion_tokens"),
                "total_tokens": count("total_tokens"),
                "finish_reason": out["choices"][0].get("finish_reason") if ok and isinstance(out, dict) else None,
                "output_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest() if ok and text is not None else None,
            })
        except Exception:  # noqa: BLE001 - a broken trace must not break the request it describes
            pass

    def _request(self, path: str, payload: dict | None = None) -> dict:
        method = "POST" if payload is not None else "GET"
        req = urllib.request.Request(self.base_url + path, method=method,
                                     data=json.dumps(payload).encode() if payload is not None else None,
                                     headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"})
        self.last_wait_s = self.last_attempt_s = 0.0
        body, self.last_wait_s, self.last_attempt_s = urlopen_retrying(req, self.timeout_s, what=f"{method} {path}",
                                                                       max_tries=self.max_tries, max_wait=self.max_wait_s)
        try:
            return json.loads(body)
        except ValueError as e:
            raise RuntimeError(f"the reply to {method} {path} is not JSON (is the base URL the OpenAI-compatible one, "
                               f"ending in /v1?): {body[:200]!r}") from e

    def _first_model(self) -> str:
        try:
            return self._request("/models")["data"][0]["id"]
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(f"cannot list models at {self.base_url}/models ({type(e).__name__}: {e}); "
                               "set CARERELAY_LLM_MODEL or start the server") from e

    def describe(self) -> dict:
        return {"backend": "openai_compatible", "base_url": self.base_url, "model": self.model,
                "temperature": self.temperature, "max_tokens": self.max_tokens, "seed": self.seed, "extra_body": self.extra_body}

    def chat(self, messages: list[dict], json_schema: dict | None = None, schema_name: str = "reply") -> dict:
        payload = {"model": self.model, "messages": messages, "temperature": self.temperature,
                   "max_tokens": self.max_tokens}
        if self.seed is not None:
            payload["seed"] = self.seed
        payload.update(self.extra_body)
        mode = "text"
        if json_schema is not None and self.guided_json_supported:
            payload["response_format"] = {"type": "json_schema",
                                          "json_schema": {"name": schema_name, "schema": json_schema, "strict": True}}
            mode = "guided_json_schema"
        elif json_schema is not None:
            last = messages[-1]["content"]   # a string, or a list of parts (text and images) for a vision model
            hinted = (last + [{"type": "text", "text": _schema_hint(json_schema)}] if isinstance(last, list)
                      else last + "\n\n" + _schema_hint(json_schema))
            payload["messages"] = messages[:-1] + [{**messages[-1], "content": hinted}]
            mode = "prompted_json"
        started = time.perf_counter()
        try:
            out = self._request("/chat/completions", payload)
        except urllib.error.HTTPError as e:
            self._trace(started, messages, json_schema, schema_name, mode, error=f"HTTP {e.code}")
            body = e.read().decode(errors="replace")[:400]
            if e.code in (400, 422) and "chat_template_kwargs" in payload and "chat_template_kwargs" in body:
                raise RuntimeError(f"LLM HTTP {e.code}: the server rejected chat_template_kwargs, the extra request field "
                                   "from CARERELAY_LLM_EXTRA_BODY that turns thinking off. Rerun scripts/amd_llm_run.sh "
                                   "with --extra-body none (or set CARERELAY_LLM_EXTRA_BODY to {}). Server said: " + body) from e
            if mode == "guided_json_schema" and e.code in (400, 422) and \
                    re.search(r"response_format|json_schema|guided|structured|grammar|xgrammar", body, re.I):
                self.guided_json_supported = False  # server does not support guided JSON: prompt for it instead
                print(f"[llm_client] the server rejected response_format json_schema (HTTP {e.code}: {body[:160]}); "
                      "using prompted JSON (schema in the prompt, JSON read from the reply) for the rest of this client",
                      file=sys.stderr, flush=True)
                return self.chat(messages, json_schema, schema_name)
            about_rf = re.search(r"response_format|json_schema|guided|structured|grammar|xgrammar", body, re.I)
            hint = (" (if this says the server does not accept response_format json_schema, rerun with "
                    "CARERELAY_LLM_GUIDED_JSON=0 to use prompted JSON)") if mode == "guided_json_schema" and (
                        e.code in (400, 422) or (500 <= e.code <= 599 and about_rf)) else ""
            raise RuntimeError(f"LLM HTTP {e.code}: {body}{hint}") from e
        except Exception as e:
            self._trace(started, messages, json_schema, schema_name, mode, error=type(e).__name__)
            raise
        latency = self.last_attempt_s   # the successful try's round trip: failed tries and waits left out
        try:
            msg = out["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as e:
            self._trace(started, messages, json_schema, schema_name, mode, out=out, error="no choices in the reply")
            raise RuntimeError(f"LLM response has no choices: {str(out)[:300]}") from e
        text = strip_thinking(msg.get("content") or "")  # thinking text that leaked into content
        parsed = extract_json(text) if json_schema is not None else None
        self._trace(started, messages, json_schema, schema_name, mode, out=out, text=text)
        return {"text": text, "json": parsed, "latency_s": round(latency, 3), "usage": out.get("usage"),
                "json_mode": mode, "finish_reason": out["choices"][0].get("finish_reason")}


def hide_broken_torchaudio() -> str | None:
    """Kaggle's image ships a torchaudio built for another CUDA than its torch ("PyTorch has CUDA version 13.x whereas
    TorchAudio has CUDA version 12.8"). transformers imports torchaudio whenever `find_spec` sees it, so loading any
    model died with "Could not import module 'Qwen3ForCausalLM'". Nothing in CareRelay needs torchaudio: when it cannot
    be imported, register it as absent (sys.modules[name] = None makes find_spec return None and `import torchaudio`
    raise ModuleNotFoundError, exactly as if it were not installed). Returns the one-line cause when hidden, else None."""
    import importlib.util
    import subprocess
    if importlib.util.find_spec("torchaudio") is None:
        return None
    probe = subprocess.run([sys.executable, "-c", "import torchaudio"], capture_output=True, text=True)
    if probe.returncode == 0:
        return None
    sys.modules["torchaudio"] = None  # type: ignore[assignment]
    return (probe.stderr.strip().splitlines() or ["import failed"])[-1][:300]


class TransformersChat:
    """In-process fallback (Kaggle without vLLM). Same chat() contract; JSON is prompted and extracted."""

    def __init__(self, model_id: str, temperature: float = 0.0, max_tokens: int = 700, dtype: str = "auto"):
        import torch
        hidden = hide_broken_torchaudio()
        if hidden:
            print(f"[llm_client] torchaudio cannot load ({hidden}); hidden from transformers, nothing in CareRelay needs it",
                  file=sys.stderr)
        from transformers import AutoModelForCausalLM, AutoTokenizer
        self.torch = torch
        self.model = model_id  # name string, like OpenAIChat.model
        self.temperature, self.max_tokens = temperature, max_tokens
        torch_dtype = {"auto": "auto", "fp16": torch.float16, "bf16": torch.bfloat16}.get(dtype, "auto")
        try:
            self.tok = AutoTokenizer.from_pretrained(model_id)
            try:  # device_map="auto" spreads a large model over both T4s; it needs the accelerate package
                self.llm = AutoModelForCausalLM.from_pretrained(model_id, torch_dtype=torch_dtype, device_map="auto")
            except (ImportError, ValueError) as e:
                if "accelerate" not in str(e):
                    raise
                self.llm = AutoModelForCausalLM.from_pretrained(model_id, torch_dtype=torch_dtype)
                self.llm.to("cuda" if torch.cuda.is_available() else "cpu")
        except Exception as e:  # noqa: BLE001 - transformers hides the real cause behind "Could not import module ..."
            cause = e
            while cause.__cause__ is not None:
                cause = cause.__cause__
            raise RuntimeError(f"transformers could not load {model_id}: {cause}") from e
        self.llm.eval()

    def describe(self) -> dict:
        return {"backend": "transformers", "model": self.model, "temperature": self.temperature, "max_tokens": self.max_tokens}

    def chat(self, messages: list[dict], json_schema: dict | None = None, schema_name: str = "reply") -> dict:
        torch = self.torch
        if json_schema is not None:
            messages = messages[:-1] + [{**messages[-1], "content": messages[-1]["content"] + "\n\n" + _schema_hint(json_schema)}]
        # return_dict works on transformers 4.4x and 5.x (5.x returns a dict by default); enable_thinking=False turns off
        # Qwen3-style thinking and is ignored by chat templates that do not use it
        enc = self.tok.apply_chat_template(messages, add_generation_prompt=True, return_tensors="pt", return_dict=True,
                                           enable_thinking=False)
        ids = enc["input_ids"].to(self.llm.device)
        t0 = time.perf_counter()
        with torch.inference_mode():
            kwargs = {"max_new_tokens": self.max_tokens, "pad_token_id": self.tok.eos_token_id,
                      "attention_mask": enc["attention_mask"].to(self.llm.device)}
            if self.temperature > 0:
                kwargs.update(do_sample=True, temperature=self.temperature)
            else:
                kwargs.update(do_sample=False)
            gen = self.llm.generate(ids, **kwargs)
        latency = time.perf_counter() - t0
        new = gen[0, ids.shape[1]:]
        text = self.tok.decode(new, skip_special_tokens=True)
        text = strip_thinking(text)
        return {"text": text, "json": extract_json(text) if json_schema is not None else None, "latency_s": round(latency, 3),
                "usage": {"prompt_tokens": int(ids.shape[1]), "completion_tokens": int(new.shape[0])},
                "json_mode": "prompted_json" if json_schema is not None else "text", "finish_reason": None}


def make_client(backend: str | None = None, **kw):
    """backend: 'openai' (default; vLLM or any OpenAI-compatible server), 'transformers:<hf model id>', or 'none'
    (no language model: returns None, and every agent stage uses its deterministic fallback)."""
    backend = backend or os.environ.get("CARERELAY_LLM_BACKEND") or "openai"
    if backend == "none":
        return None
    if backend.startswith("transformers:"):
        return TransformersChat(backend.split(":", 1)[1], **{k: v for k, v in kw.items() if k in ("temperature", "max_tokens")})
    return OpenAIChat(**kw)


def make_photo_client(**kw):
    """The client that reads photos: the model in CARERELAY_PHOTO_MODEL when it is set (a vision model, for an endpoint
    whose model for facts and questions takes no images), else the same model as everything else."""
    model = kw.pop("model", None)
    return make_client(model=os.environ.get("CARERELAY_PHOTO_MODEL") or model, **kw)
