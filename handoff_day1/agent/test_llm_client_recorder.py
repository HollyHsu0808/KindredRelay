#!/usr/bin/env python3
"""The opt-in call recorder of llm_client.py (the app shell's AMD Runtime view), against a small OpenAI-compatible
stand-in served in this process on 127.0.0.1 (no model, no outside network): off by default with the same chat()
result as before; one metadata row per request (model, endpoint host only, latency, the server's own token usage or
None, outcome, a hash of the reply) and never the key, the prompt or the reply; error rows; bounded and thread-safe;
bound per thread / context at client creation. Stdlib only:
  python agent/test_llm_client_recorder.py
"""
from __future__ import annotations

import hashlib
import json
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from llm_client import CallRecorder, OpenAIChat, start_call_recording, stop_call_recording  # noqa: E402

SECRET = "sk-test-not-a-real-key-7f3a"
PROMPT = "Patient note: the follow-up appointment is on Thursday."
REPLY = '{"facts": [{"type": "follow_up", "quote": "the follow-up appointment is on Thursday"}]}'
SCHEMA = {"type": "object", "properties": {"facts": {"type": "array"}}}
RESULT_KEYS = {"text", "json", "latency_s", "usage", "json_mode", "finish_reason"}   # chat()'s contract before the trace


class Stub(BaseHTTPRequestHandler):
    """Answers each POST with the next scripted (status, body) of the server's queue; the last one repeats."""

    def log_message(self, *args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        self.server.seen.append({"body": body, "auth": self.headers.get("Authorization")})
        status, reply = self.server.script[0] if len(self.server.script) == 1 else self.server.script.pop(0)
        data = json.dumps(reply(body) if callable(reply) else reply).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def completion(text: str = REPLY, usage: dict | None = None, model: str = "served-alias") -> dict:
    out = {"id": "x", "object": "chat.completion", "model": model,
           "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}]}
    if usage is not None:
        out["usage"] = usage
    return out


class StubServer:
    def __init__(self, *script):
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Stub)
        self.httpd.script, self.httpd.seen = list(script), []
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.httpd.server_address[1]}/v1"

    @property
    def seen(self) -> list:
        return self.httpd.seen


def client(base_url: str, **kw) -> OpenAIChat:
    return OpenAIChat(base_url=base_url, model="Gemma-4-31B-IT", api_key=SECRET, timeout_s=10, max_tries=1, **kw)


def messages(prompt: str = PROMPT) -> list:
    return [{"role": "system", "content": "Reply with JSON."}, {"role": "user", "content": prompt}]


class TestOffByDefault(unittest.TestCase):
    def test_no_recorder_and_the_same_result(self):
        with StubServer((200, completion(usage={"prompt_tokens": 40, "completion_tokens": 12}))) as srv:
            c = client(srv.base_url)
            self.assertIsNone(c.recorder)
            r = c.chat(messages(), json_schema=SCHEMA, schema_name="facts")
        self.assertEqual(set(r), RESULT_KEYS)
        self.assertEqual(r["text"], REPLY)
        self.assertEqual(r["usage"], {"prompt_tokens": 40, "completion_tokens": 12})
        self.assertEqual(srv.seen[0]["auth"], f"Bearer {SECRET}")   # the request itself is unchanged

    def test_a_client_made_before_or_after_recording_has_none(self):
        before = OpenAIChat(base_url="http://127.0.0.1:9/v1", model="m")
        token = start_call_recording(CallRecorder())
        during = OpenAIChat(base_url="http://127.0.0.1:9/v1", model="m")
        stop_call_recording(token)
        after = OpenAIChat(base_url="http://127.0.0.1:9/v1", model="m")
        self.assertIsNone(before.recorder)
        self.assertIsNotNone(during.recorder, "bound at creation, kept after recording stops")
        self.assertIsNone(after.recorder)


class TestRows(unittest.TestCase):
    def setUp(self):
        self.rec = CallRecorder()
        self.token = start_call_recording(self.rec)

    def tearDown(self):
        stop_call_recording(self.token)

    def test_metadata_only(self):
        usage = {"prompt_tokens": 40, "completion_tokens": 12, "total_tokens": 52}
        with StubServer((200, completion(usage=usage))) as srv:
            c = client(srv.base_url)
            r = c.chat(messages(), json_schema=SCHEMA, schema_name="facts")
        [row] = self.rec.calls()
        self.assertEqual(set(r), RESULT_KEYS, "the result carries nothing new")
        self.assertEqual((row["model"], row["served_model"], row["host"]), ("Gemma-4-31B-IT", "served-alias", "127.0.0.1"))
        self.assertEqual((row["schema"], row["json_mode"], row["images"], row["ok"], row["error"]),
                         ("facts", "guided_json_schema", 0, True, None))
        self.assertEqual((row["prompt_tokens"], row["completion_tokens"], row["total_tokens"]), (40, 12, 52))
        self.assertEqual(row["latency_s"], r["latency_s"])
        self.assertEqual(row["wait_s"], 0.0)
        self.assertEqual(row["finish_reason"], "stop")
        self.assertEqual(row["output_sha256"], hashlib.sha256(r["text"].encode("utf-8")).hexdigest())
        self.assertEqual(row["seq"], 1)
        dumped = json.dumps(row)
        for private in (SECRET, PROMPT, REPLY, "Thursday", "/v1", "127.0.0.1:"):
            self.assertNotIn(private, dumped)

    def test_host_only_from_a_url_with_credentials(self):
        c = OpenAIChat(base_url="https://user:hunter2@developer.amd.com.cn/radeon/api/v1?api-key=abc", model="m",
                       api_key=SECRET)
        c._trace(0.0, messages(), None, "reply", "text", out=completion(), text="ok")
        [row] = self.rec.calls()
        self.assertEqual(row["host"], "developer.amd.com.cn")
        for private in ("hunter2", "user", "api-key", "abc", "radeon", SECRET):
            self.assertNotIn(private, json.dumps(row))

    def test_usage_absent_or_odd_is_none_never_estimated(self):
        odd = {"prompt_tokens": "40", "completion_tokens": True, "total_tokens": -1}
        with StubServer((200, completion()), (200, completion(usage=odd))) as srv:
            c = client(srv.base_url)
            c.chat(messages())
            c.chat(messages())
        for row in self.rec.calls():
            self.assertEqual((row["prompt_tokens"], row["completion_tokens"], row["total_tokens"]), (None, None, None))
            self.assertTrue(row["ok"])

    def test_http_error_is_a_row_and_still_raises(self):
        with StubServer((400, {"error": {"message": "bad request: messages too long"}})) as srv:
            c = client(srv.base_url)
            with self.assertRaisesRegex(RuntimeError, "LLM HTTP 400"):
                c.chat(messages(), json_schema=SCHEMA, schema_name="facts")
        [row] = self.rec.calls()
        self.assertEqual((row["ok"], row["error"], row["latency_s"], row["output_sha256"]), (False, "HTTP 400", None, None))
        self.assertIsInstance(row["elapsed_s"], float)

    def test_guided_json_rejected_then_prompted(self):
        with StubServer((400, {"error": {"message": "response_format json_schema is not supported"}}),
                        (200, completion(usage={"prompt_tokens": 50, "completion_tokens": 9}))) as srv:
            c = client(srv.base_url)
            r = c.chat(messages(), json_schema=SCHEMA, schema_name="facts")
        self.assertEqual(r["json_mode"], "prompted_json")
        rows = self.rec.calls()
        self.assertEqual([(x["ok"], x["error"], x["json_mode"]) for x in rows],
                         [(False, "HTTP 400", "guided_json_schema"), (True, None, "prompted_json")])

    def test_connection_failure_is_a_row(self):
        c = client("http://127.0.0.1:9/v1")   # nothing listens on the discard port
        with self.assertRaises(Exception):
            c.chat(messages())
        [row] = self.rec.calls()
        self.assertFalse(row["ok"])
        self.assertTrue(row["error"])
        self.assertNotIn(SECRET, json.dumps(row))

    def test_reply_without_choices_is_a_row(self):
        with StubServer((200, {"object": "chat.completion", "usage": {"prompt_tokens": 3, "completion_tokens": 0}})) as srv:
            with self.assertRaisesRegex(RuntimeError, "no choices"):
                client(srv.base_url).chat(messages())
        [row] = self.rec.calls()
        self.assertEqual((row["ok"], row["error"], row["prompt_tokens"]), (False, "no choices in the reply", 3))

    def test_image_parts_are_counted_not_kept(self):
        parts = [{"type": "text", "text": "Copy every word."},
                 {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,/9j/AAAA"}}]
        with StubServer((200, completion(text="Paracetamol 500 mg"))) as srv:
            client(srv.base_url).chat([{"role": "user", "content": parts}])
        [row] = self.rec.calls()
        self.assertEqual((row["images"], row["schema"], row["json_mode"]), (1, None, "text"))
        self.assertNotIn("base64", json.dumps(row))

    def test_a_broken_recorder_never_breaks_the_call(self):
        class Broken(CallRecorder):
            def record(self, row):
                raise OSError("disk full")
        token = start_call_recording(Broken())
        try:
            with StubServer((200, completion())) as srv:
                r = client(srv.base_url).chat(messages())
        finally:
            stop_call_recording(token)
        self.assertEqual(r["text"], REPLY)


class TestRecorder(unittest.TestCase):
    def test_bounded_and_thread_safe(self):
        rec = CallRecorder(maxlen=5)

        def burst():
            for _ in range(50):
                rec.record({"ok": True})
        threads = [threading.Thread(target=burst) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
        rows = rec.calls()
        self.assertEqual(rec.total, 400)
        self.assertEqual([r["seq"] for r in rows], [396, 397, 398, 399, 400])
        rows[0]["ok"] = False
        self.assertTrue(rec.calls()[0]["ok"], "calls() returns copies")
        rec.clear()
        self.assertEqual((rec.calls(), rec.total), ([], 400))

    def test_binding_is_per_thread(self):
        rec = CallRecorder()
        token = start_call_recording(rec)
        seen = {}
        try:
            t = threading.Thread(target=lambda: seen.update(other=OpenAIChat(base_url="http://127.0.0.1:9/v1", model="m").recorder))
            t.start()
            t.join(timeout=10)
            here = OpenAIChat(base_url="http://127.0.0.1:9/v1", model="m").recorder
        finally:
            stop_call_recording(token)
        self.assertIs(here, rec)
        self.assertIsNone(seen["other"], "another thread (another browser session's script run) never gets this recorder")


if __name__ == "__main__":
    unittest.main(verbosity=2)
