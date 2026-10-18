#!/usr/bin/env python3
"""Scripted OpenAI-compatible server for wiring and tests WITHOUT a GPU (stdlib only).

It is NOT a language model. It answers the Case Agent's stages with fixed, rule-following replies (mode "good",
built from the care-case reference answers) or with rule-breaking replies (mode "bad", to exercise the guardrails,
the retry and the safe fallback). Leo can point the backend at it to build the UI before a real LLM runs.

Usage:
  python fake_llm_server.py --port 8011 --mode good       # then CARERELAY_LLM_BASE_URL=http://127.0.0.1:8011/v1
  python fake_llm_server.py --port 8011 --api-key K       # like `vllm serve --api-key K`: /v1 paths need "Bearer K"
GET /metrics serves a few vLLM-named Prometheus counters (requests, tokens, latency), unauthenticated as in vLLM.
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

CARE_CASES = Path(__file__).resolve().parents[1] / "care_cases"

MODE = "good"
REJECT_GUIDED = False
API_KEY = ""   # empty: no authentication (vLLM without --api-key)
# vLLM's AuthenticationMiddleware guards these path prefixes when --api-key is set; /metrics and /health stay open
GUARDED_PREFIX = ("/v1", "/v2", "/inference", "/cohere")
STATS = {"requests": 0, "prompt_tokens": 0, "generation_tokens": 0, "e2e_sum": 0.0}
STATS_LOCK = threading.Lock()
A_REPLY = ("The current instruction from the clinician says: \"Please ask the caregiver for assistance before getting out of bed.\" "
           "(source src-A-001, revision r1). Looking steady does not change this instruction, so please help her before she gets up. "
           "I've added a question for the care team about whether this instruction should change, and flagged that the handover "
           "note left the condition out. Before she gets out of bed, what will you do?")
B_REPLY = ("No. The recording has always said 11:00 a.m. The first transcript wrongly said 10:00 a.m.; it was corrected after the "
           "recording was checked (src-B-001, transcript revision r2). That is a transcript correction, not a new instruction from "
           "the clinic. The updated appointment items are waiting for review.")
# the third real run (Qwen3-8B, Kaggle, 2026-10-14), family statement "The clinic phoned me, it's now 2 p.m.": it passed the
# guardrails of that day, but quotes the get-up instruction, not the appointment sentence the claim is about
RUN3_FAMILY_REPLY = ("The family member reported the clinic called, but this is not a clinician instruction. The current instruction is: "
                     "\"Please ask the caregiver for assistance before getting out of bed.\" (source_id: src-A-001, revision: r1, "
                     "segment_id: s1). Both the family statement and the clinician instruction have been recorded for the care team "
                     "to confirm. No action is needed now.")
# the first real run, same statement: the claim as a fact and a stray teach-back question
RUN1_FAMILY_REPLY = "The clinic called you at 2 p.m. Before she gets out of bed, what will you do?"
FAMILY_REF_RX = re.compile(r'this claim is about, word for word in double quotes with its source id: "(.+?)" '
                           r'\(source ([^,]+), revision ([^,]+), segment ([^):]+)')


def family_answer(user: str) -> dict:
    """A family statement. Good mode quotes the case sentence the agent's prompt names (the one the claim is about),
    or says that no case source covers the claim. Bad mode answers with the third real run's reply first (an
    unrelated source sentence; when the claim really is about getting up, that sentence is the right one, so the
    first run's reply is used instead) and, on the retry, with the first run's (the claim as a fact plus a question)."""
    nofix = {"item_id": "", "content": ""}
    m = FAMILY_REF_RX.search(user)
    if MODE == "bad":
        retry = "YOUR PREVIOUS REPLY WAS REJECTED" in user
        about_get_up = bool(m) and "getting out of bed" in m.group(1)
        return {"reply": RUN1_FAMILY_REPLY if retry or about_get_up else RUN3_FAMILY_REPLY,
                "citations": [{"source_id": "src-A-001", "revision": "r1", "segment_id": "s1"}], "situation": "family_claim",
                "pending_item": {"type": "none" if retry else "conflict", "text": "" if retry else "Family member reported the clinic called."},
                "handover_fix": {"item_id": "ho-A-mobility", "content": "Mobility: help her before she gets out of bed (assistance required)."}
                if retry else nofix}
    if m:
        text, sid, rev, seg = m.groups()
        reply = (f"Thank you for letting us know. A report from family cannot change the case on its own. The current source "
                 f"({sid}) says: \"{text}\" Both have been recorded for the care team to confirm.")
        cites = [{"source_id": sid, "revision": rev, "segment_id": seg.strip()}]
    elif "no case source is about this claim" in user:
        reply = ("Thank you for letting us know. A report from family cannot change the case on its own. Nothing in the case "
                 "sources says this yet. It has been recorded for the care team to confirm.")
        cites = []
    else:  # an older agent prompt that names no sentence
        reply = ("Thank you. A phone message cannot change the appointment on its own. The recording says 11:00 a.m.; "
                 "I have recorded both for the care team to confirm.")
        cites = [{"source_id": "src-B-001-tx", "revision": "r2", "segment_id": "seg-02"}]
    return {"reply": reply, "citations": cites, "situation": "family_claim",
            "pending_item": {"type": "conflict", "text": "family statement recorded next to the current source"}, "handover_fix": nofix}


def answer_for(user: str) -> dict:
    none = {"type": "none", "text": ""}
    nofix = {"item_id": "", "content": ""}
    if "A family member (" in user:  # the framing line, not a pending item that mentions family_statement
        return family_answer(user)
    if MODE == "bad":
        return {"reply": "Yes, she can get up on her own now. The clinic changed the appointment, it was moved.", "citations": [],
                "situation": "other", "pending_item": none, "handover_fix": {"item_id": "ho-A-mobility", "content": "Mobility: no assistance needed."}}
    if "Did the doctor" in user:
        return {"reply": B_REPLY, "citations": [{"source_id": "src-B-001-tx", "revision": "r2", "segment_id": "seg-02"}],
                "situation": "question_about_correction", "pending_item": none, "handover_fix": nofix}
    return {"reply": A_REPLY, "citations": [{"source_id": "src-A-001", "revision": "r1", "segment_id": "s1"}],
            "situation": "question_about_instruction",
            "pending_item": {"type": "needs_clinical_confirmation", "text": "Can Resident R now get out of bed without assistance?"},
            "handover_fix": {"item_id": "ho-A-mobility", "content": "Mobility: ask the caregiver for help before she gets out of bed (assistance required)."}}


SMOKE_PROMPT = 'Reply with JSON {"ok": true}.'   # the smoke test of the Kaggle notebook (cell 6) and scripts/amd_llm_run.sh
GARBLED_REPLY = "ok ok<pad><pad> tru tru ::: {{ okokok"   # what a model that does not run well looks like: no JSON


def photo_reading() -> str:
    """A vision request (the family timeline's photo reader): the text printed on the sample medication list
    (care_cases/photos/make_sample_photos.py), whatever the image; bad mode misreads 15 mg as 1.5 mg, the kind of error
    the caregiver's check is there to catch."""
    src = (CARE_CASES / "photos" / "make_sample_photos.py").read_text(encoding="utf-8")
    text = "\n".join(ast.literal_eval(src.split("TEXT = ", 1)[1].split("\n]", 1)[0] + "\n]"))
    return text.replace("Lansoprazole 15 mg", "Lansoprazole 1.5 mg") if MODE == "bad" else text


def episode_facts(user: str) -> dict:
    """The family timeline's fact extraction (agent/episode.py llm_extractor): the medication list of the demo story
    (u08's recorded extraction) when the update is that list, a read of its photo included; the recorded extraction of
    any other update of the demo story whose text is in the prompt (e.g. step 5 of DEMO_RECORDING_zh-TW.md, the nurse's
    u07); nothing for any other text. Bad mode adds a fact whose quote is not in the update (the grounding check must
    reject it)."""
    facts = []
    story = json.loads((CARE_CASES / "episode_hip_fracture.json").read_text(encoding="utf-8"))
    if "STOP taking Ibuprofen" in user and "Lansoprazole 15 mg" in user:
        facts = next(u for u in story["updates"] if u["update_id"] == "u08")["recorded_extraction"]
    else:
        facts = next((u["recorded_extraction"] for u in story["updates"]
                      if (u.get("text") or "").strip() and u["text"].strip() in user and u.get("recorded_extraction")), [])
    if MODE == "bad":
        facts = facts + [{"type": "medication", "name": "Warfarin", "dose": "5 mg", "status": "new", "quote": "Warfarin 5 mg once a day"}]
    return {"facts": facts}


def respond(body: dict) -> str:
    msgs = body.get("messages", [])
    user = msgs[-1]["content"] if msgs else ""
    if isinstance(user, list):   # OpenAI content parts: text and images
        if any(isinstance(p, dict) and p.get("type") == "image_url" for p in user):
            return photo_reading()
        user = "\n\n".join(p.get("text", "") for p in user if isinstance(p, dict))
    if user.startswith(SMOKE_PROMPT):
        # Like vLLM: with response_format (guided decoding) the schema forces valid JSON even from a broken model, so
        # bad mode answers {"ok": true} there too. Without it, bad mode is garbled text: only the unconstrained smoke
        # call of scripts/amd_llm_run.sh can catch a model that does not run well.
        return '{"ok": true}' if MODE == "good" or body.get("response_format") else GARBLED_REPLY
    name = ((body.get("response_format") or {}).get("json_schema") or {}).get("name", "")
    if not name:  # prompted-JSON fallback: infer the stage from the prompt
        name = ("episode_answer" if QA_MARKER in user else "facts" if "List every fact this update states" in user else "rewrite" if "Rewrite this" in user else "restate" if "teach-back question" in user and "answered" in user
                else "instructions" if "List every care instruction" in user else "answer" if "CASE SOURCES" in user else "text")
    if name == "episode_answer":
        return json.dumps(episode_answer(user))
    if name == "facts":
        return json.dumps(episode_facts(user))
    if name == "answer":
        return json.dumps(answer_for(user))
    if name == "restate":
        if MODE == "bad":
            return json.dumps({"reply": "Good job, that is correct."})
        return json.dumps({"reply": "Thank you. The instruction says: \"Please ask the caregiver for assistance before getting out of bed.\" "
                                    "Your plan does not mention helping her before she gets out of bed."})
    if name == "rewrite":
        m = re.search(r'Current content: "(.*?)"(?:\n|$)', user, re.S)  # stop before an appended schema hint
        cur = m.group(1) if m else ""
        return json.dumps({"content": cur if MODE == "bad" else rewrite_for(user, cur)})   # bad: keeps "Thursday"/"11:00", "10:00"
    if name == "instructions":
        seg = re.search(r"^\[([^\]]+)\] (.+)$", user, re.M)
        if not seg or MODE == "bad":
            return json.dumps({"instructions": [{"action": "invented", "condition": "", "time": "", "quote": "not in transcript", "segment_id": "x", "supersedes": ""}]})
        return json.dumps({"instructions": extract_for(user) or
                           [{"action": "follow advice", "condition": "", "time": "", "quote": seg.group(2)[:60], "segment_id": seg.group(1), "supersedes": ""}]})
    return "This is a scripted reply from the fake LLM server."


QA_MARKER = "EPISODE UPDATES (numbered sentences"   # agent/episode_qa.py's prompt
QA_LINE_RX = re.compile(r"^ ([0-9A-Za-z_-]+\.\d+)(?: \[([^\]]*)\])?: (.+)$", re.M)   # u05.4, c01.2 (added on the page)
QA_STALE = ("EARLIER", "PAST", "DONE SINCE", "GIVEN BEFORE", "CONTRADICTED", "ADDED LATE")


def episode_answer(user: str) -> dict:
    """A family member's question about the episode: choose the sentences that answer it. Good mode cites the current
    sentence sharing the most words with the question (a care-team one before a family report); bad mode first cites a
    sentence id that does not exist, then on the retry says "no" while citing a sentence, so the backend falls back to
    its own choice."""
    if MODE == "bad":
        if "YOUR PREVIOUS REPLY WAS REJECTED" in user:
            return {"covered": "no", "citations": ["u05.4"]}
        return {"covered": "yes", "citations": ["u99.9"]}
    q = re.search(r'^QUESTION[^:]*: "(.*)"$', user, re.M)
    qwords = {w for w in re.findall(r"[a-z]+", (q.group(1) if q else "").lower()) if len(w) > 3}
    best, best_score = None, 0
    for sid, label, text in QA_LINE_RX.findall(user):
        label = label or ""
        if any(s in label for s in QA_STALE):
            continue
        score = len(qwords & {w for w in re.findall(r"[a-z]+", text.lower()) if len(w) > 3}) - (0.5 if "FAMILY" in label else 0)
        if score > best_score:
            best, best_score = sid, score
    return {"covered": "partly", "citations": [best]} if best else {"covered": "no", "citations": []}


def rewrite_for(user: str, cur: str) -> str:
    """Good-mode rewrite: a superseding source ('its time changed from "Thursday 11:00 a.m." to "Wednesday 4:00 p.m."')
    swaps the weekday and the clock in the one clause that names both (another time in the same item is left alone,
    as a careful writer would) and keeps every other word; a transcript correction ('"10:00 a.m." is now
    "11:00 a.m."') replaces the corrected words. Both pairs are read from the agent's prompt."""
    m = re.search(r'its time changed from "([^"]+)" to "([^"]+)"', user)
    if m:
        (ow, oc), (nw, nc) = m.group(1).split(" ", 1), m.group(2).split(" ", 1)
        ow_rx, oc_rx = re.compile(r"\b" + ow + r"\b", re.I), re.compile(r"\b" + oc.split(":")[0] + r"(?::\d{2})?\s*[ap]\.m\.", re.I)
        parts = re.split(r"((?<=[ap]\.m\.)\s+|(?<![ap]\.m)[.;:!?](?:\s+|$))", cur, flags=re.I)   # same clause rule as change_engine
        hits = [i for i, part in enumerate(parts) if ow_rx.search(part) and oc_rx.search(part)]
        if len(hits) != 1:
            return cur
        parts[hits[0]] = oc_rx.sub(nc, ow_rx.sub(nw, parts[hits[0]], count=1), count=1)
        return "".join(parts)
    m = re.search(r'corrected after checking the recording: "([^"]+)" is now "([^"]+)"', user)
    if m:
        return cur.replace(m.group(1), m.group(2))
    return cur.replace("10:00", "11:00")


def extract_for(user: str) -> list[dict] | None:
    """Good-mode extractor for the Case C recording: a follow-up segment with a readable time becomes a proposal that
    names the active follow-up instruction it replaces (supersedes); a 'bring the ... diary' segment becomes a second,
    time-less proposal. Quotes are copied from the segment text; the time is written as the segment says it."""
    segs = re.findall(r"^\[([^\]]+)\] (.+)$", user, re.M)
    active = re.findall(r"^(ins-[\w-]+): ([^;]+);", user, re.M)
    out = []
    for sid, text in segs:
        low = text.lower()
        if "follow-up appointment" in low:
            t = re.search(r"\b(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\b.{0,6}?\b\d{1,2}(?::\d{2})?\s*[ap]\.m\.", text, re.I)
            q = re.search(r"(?:moved your |your )?follow-up appointment", text, re.I)
            quote = text[q.start():].strip() if q else text
            if quote.endswith(".") and not re.search(r"[ap]\.m\.$", quote):   # drop a sentence period, keep "p.m."
                quote = quote[:-1]
            sup = next((i for i, a in active if "follow-up" in a), "")
            out.append({"action": "attend follow-up appointment", "condition": "", "time": t.group(0) if t else "",
                        "quote": quote, "segment_id": sid, "supersedes": sup})
        elif "bring the" in low and "diary" in low:   # no condition: the segment states none (the grounding check would reject it)
            q = re.search(r"bring the [^.]*diary", text, re.I)
            out.append({"action": "bring blood pressure diary", "condition": "", "time": "",
                        "quote": q.group(0) if q else text.rstrip("."), "segment_id": sid, "supersedes": ""})
    return out or None


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code: int, obj: dict):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _authorized(self) -> bool:
        if API_KEY and self.path.startswith(GUARDED_PREFIX) and self.headers.get("Authorization") != "Bearer " + API_KEY:
            self._send(401, {"error": "Unauthorized"})
            return False
        return True

    def _metrics(self):
        name = f'model_name="fake-carerelay-{MODE}"'
        with STATS_LOCK:
            st = dict(STATS)
        rows = [("vllm:request_success_total", "counter", f'{{finished_reason="stop",{name}}}', st["requests"]),
                ("vllm:prompt_tokens_total", "counter", f"{{{name}}}", st["prompt_tokens"]),
                ("vllm:generation_tokens_total", "counter", f"{{{name}}}", st["generation_tokens"]),
                ("vllm:e2e_request_latency_seconds_sum", "histogram", f"{{{name}}}", round(st["e2e_sum"], 6)),
                ("vllm:e2e_request_latency_seconds_count", "histogram", f"{{{name}}}", st["requests"]),
                ("vllm:num_requests_running", "gauge", f"{{{name}}}", 0)]
        b = "".join(f"# TYPE {n} {t}\n{n}{lab} {v}\n" for n, t, lab, v in rows).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if self.path.rstrip("/") == "/metrics":
            return self._metrics()
        if not self._authorized():
            return None
        if self.path.rstrip("/").endswith("/models"):
            return self._send(200, {"object": "list", "data": [{"id": f"fake-carerelay-{MODE}", "object": "model"}]})
        self._send(404, {"error": "not found"})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        if not self._authorized():
            return None
        if not self.path.rstrip("/").endswith("/chat/completions"):
            return self._send(404, {"error": "not found"})
        if REJECT_GUIDED and body.get("response_format"):
            return self._send(400, {"error": {"message": "response_format is not supported by this server"}})
        t0 = time.perf_counter()
        text = respond(body)
        usage = {"prompt_tokens": len(json.dumps(body)) // 4, "completion_tokens": len(text) // 4}
        with STATS_LOCK:
            STATS["requests"] += 1
            STATS["prompt_tokens"] += usage["prompt_tokens"]
            STATS["generation_tokens"] += usage["completion_tokens"]
            STATS["e2e_sum"] += time.perf_counter() - t0
        self._send(200, {"id": "fake", "object": "chat.completion", "model": body.get("model"),
                         "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
                         "usage": usage})


def main() -> int:
    global MODE, REJECT_GUIDED, API_KEY
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8011)
    ap.add_argument("--mode", choices=["good", "bad"], default="good")
    ap.add_argument("--reject-guided", action="store_true", help="answer 400 to response_format (tests the prompted-JSON fallback)")
    ap.add_argument("--api-key", default="", help="require 'Authorization: Bearer KEY' on /v1 paths, as vLLM does")
    args = ap.parse_args()
    MODE, REJECT_GUIDED, API_KEY = args.mode, args.reject_guided, args.api_key
    print(f"fake OpenAI-compatible server ({MODE}) on http://127.0.0.1:{args.port}/v1", flush=True)
    ThreadingHTTPServer(("127.0.0.1", args.port), H).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
