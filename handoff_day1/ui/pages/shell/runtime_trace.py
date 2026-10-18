"""The AMD Runtime view of the app shell: the model calls this browser session made, from llm_client's opt-in call
recorder (model, endpoint host, latency, the server's token usage), joined with what the backend's checks did with each
reply. The join uses only logs the family timeline already keeps in its session (the extractor's, the answerer's and the
photo reader's .log lists, and the episode's entries); no page or engine code is changed for it. At the top of the page
and in the sidebar panel, a session summary: calls by the host they were sent to (the AMD Token Factory endpoint or
other hosts), and per model the stages of its calls (its role), p50 latency and the server's token usage. Metadata
only: no prompt, reply, image or key is stored or shown, and the API key is never read here.
"""
from __future__ import annotations

import hashlib
import os
import statistics
from urllib.parse import urlsplit

from llm_client import CallRecorder, start_call_recording, stop_call_recording

TOKEN_FACTORY_HOST = "developer.amd.com.cn"   # README.md:25, the API base URL from the Token Factory user manual
TOKEN_FACTORY_LABEL = "Inference: AMD Token Factory endpoint (AMD Developer Hackathon)"
RECORDER_KEY = "kr_runtime_recorder"
FAMILY_PARAMS_KEY = "kr_family_query_params"
LAST_PAGE_KEY = "kr_last_page"
MAX_CALLS = 100
HELD_REASON = "evidence verification requires review"   # episode.py's reason for a fact the verifier withholds
PHOTO_CHECK = "draft text: the caregiver checks every line against the photo before it is added (no automatic gate)"


# ------------------------------------------------------------------ the session's recorder
def session_recorder(state) -> CallRecorder:
    """This browser session's recorder, kept in its session state (each session sees only its own calls)."""
    rec = state.get(RECORDER_KEY)
    if not (hasattr(rec, "record") and hasattr(rec, "calls")):
        rec = state[RECORDER_KEY] = CallRecorder(MAX_CALLS)
    return rec


def activate(recorder):
    return start_call_recording(recorder)


def deactivate(token) -> None:
    stop_call_recording(token)


# ------------------------------------------------------------------ the family timeline's query parameters
def restore_family_params(st, on_family: bool) -> None:
    """Moving to another page clears the address's query parameters; coming back to the family timeline puts the last
    ones back (a family-space link ?family=...&as=..., text size), so a family member is not dropped into a private copy."""
    state = st.session_state
    if on_family and state.get(LAST_PAGE_KEY) == "other" and not st.query_params.to_dict() and state.get(FAMILY_PARAMS_KEY):
        st.query_params.update(state[FAMILY_PARAMS_KEY])


def remember_page(st, on_family: bool) -> None:
    if on_family:
        st.session_state[FAMILY_PARAMS_KEY] = st.query_params.to_dict()
    st.session_state[LAST_PAGE_KEY] = "family" if on_family else "other"


# ------------------------------------------------------------------ what the page shows
def endpoint_status(env=None) -> dict:
    """The configured endpoint, by host only. A live model is configured when base URL and model are both set (the
    family timeline's own test, live_model_configured())."""
    env = os.environ if env is None else env
    base, model = (env.get("CARERELAY_LLM_BASE_URL") or "").strip(), (env.get("CARERELAY_LLM_MODEL") or "").strip()
    try:
        host = urlsplit(base).hostname if base else None
    except ValueError:
        host = None
    configured = bool(base and model)
    if not configured:
        label = ("No live model is configured in this deployment (CARERELAY_LLM_BASE_URL and CARERELAY_LLM_MODEL are not "
                 "both set): model calls would be listed here.")
    elif host == TOKEN_FACTORY_HOST:
        label = TOKEN_FACTORY_LABEL
    else:
        label = f"Inference endpoint: {host or 'unknown host'} (not the AMD Token Factory endpoint)"
    return {"configured": configured, "host": host, "token_factory": configured and host == TOKEN_FACTORY_HOST,
            "label": label, "model": model or None, "photo_model": (env.get("CARERELAY_PHOTO_MODEL") or "").strip() or None}


def stage_label(call: dict) -> str:
    if call.get("images"):
        return "Photo reading"
    return {"facts": "Fact extraction", "episode_answer": "Question answer (sentence choice)"}.get(
        call.get("schema"), call.get("schema") or "Text reply")


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


def output_checks(state) -> dict:
    """SHA-256 of a reply's text -> what the backend's checks did with that reply, from the session's existing logs."""
    checks = {}
    for row in list(getattr(state.get("answerer"), "log", None) or []):
        if isinstance(row, dict) and isinstance(row.get("text"), str) and "violations" in row:
            v = row.get("violations") or []
            checks[_sha(row["text"])] = ("passed the answer check" if not v else
                                         f"rejected by the answer check ({_plural(len(v), 'reason')}): retried, or the "
                                         "answer came from the updates' own sentences")
    entries = list(getattr(state.get("episode"), "entries", None) or [])
    for row in list(getattr(state.get("extractor"), "log", None) or []):
        if not (isinstance(row, dict) and isinstance(row.get("text"), str)):
            continue
        entry = max((e for e in entries if isinstance(e, dict) and e.get("update_id") == row.get("update_id")),
                    key=lambda e: e.get("seq") or 0, default=None)
        if not row.get("parsed"):
            verdict = "reply could not be read: no facts were taken from it"
        elif entry is None:
            verdict = "facts went through the grounding check (results on the timeline)"
        else:
            rejected = [r for r in entry.get("rejected") or [] if isinstance(r, dict)]
            held = sum(r.get("reason") == HELD_REASON for r in rejected)
            verdict = (f"{_plural(len(entry.get('facts') or []), 'fact')} kept, {len(rejected) - held} rejected by the "
                       "grounding check" + (f", {held} held by the evidence verifier" if held else ""))
        checks[_sha(row["text"])] = verdict
    return checks


def _n(x) -> str:
    return "n/a" if x is None else str(x)


def call_rows(calls: list, checks: dict) -> list:
    """Display rows, newest first. Tokens are the server's usage numbers, n/a when it sent none."""
    rows = []
    for c in reversed(calls):
        host = c.get("host") or "n/a"
        model = c.get("model") or "n/a"
        if c.get("served_model") and c["served_model"] != c.get("model"):
            model += f" (served as {c['served_model']})"
        if c.get("ok"):
            latency = f"{c['latency_s']:.2f} s" if isinstance(c.get("latency_s"), (int, float)) else "n/a"
            if c.get("wait_s"):
                latency += f" (+{c['wait_s']:.1f} s retry wait)"
            check = PHOTO_CHECK if c.get("images") else checks.get(c.get("output_sha256"), "n/a")
            result = "ok" if c.get("finish_reason") != "length" else "ok (cut off at max tokens)"
        else:
            latency = f"failed after {c['elapsed_s']:.2f} s" if isinstance(c.get("elapsed_s"), (int, float)) else "failed"
            check, result = "no reply", f"error: {c.get('error') or 'unknown'}"
        rows.append({"#": _n(c.get("seq")), "UTC": (c.get("utc") or "")[11:19] or "n/a", "Stage": stage_label(c),
                     "Model": model, "Endpoint host": host + (" (AMD Token Factory)" if host == TOKEN_FACTORY_HOST else ""),
                     "Latency": latency, "Prompt tokens": _n(c.get("prompt_tokens")),
                     "Completion tokens": _n(c.get("completion_tokens")), "Result": result, "Output check": check})
    return rows


def summary(calls: list) -> dict:
    ok = [c for c in calls if c.get("ok")]
    lat = [c["latency_s"] for c in ok if isinstance(c.get("latency_s"), (int, float))]
    usage = [c for c in ok if c.get("prompt_tokens") is not None and c.get("completion_tokens") is not None]
    return {"calls": len(calls), "ok": len(ok), "median_latency_s": statistics.median(lat) if lat else None,
            "with_usage": len(usage), "prompt_tokens": sum(c["prompt_tokens"] for c in usage),
            "completion_tokens": sum(c["completion_tokens"] for c in usage)}


def _host(c: dict) -> str:
    return c.get("host") or "unknown host"


def session_summary(calls: list) -> dict:
    """summary() plus where the calls went (by recorded host, not by configuration) and the same numbers per model, in
    the order the models were first called. A model's roles are the stages of its own calls (stage_label: the reply
    schema it asked for, or that it carried a photo), not a model -> role map."""
    amd = sum(c.get("host") == TOKEN_FACTORY_HOST for c in calls)
    by_model: dict = {}
    for c in calls:
        by_model.setdefault(c.get("model") or "n/a", []).append(c)
    per_model = [{"model": m, "roles": list(dict.fromkeys(stage_label(c) for c in rows)),
                  "hosts": list(dict.fromkeys(_host(c) for c in rows)), **summary(rows)} for m, rows in by_model.items()]
    return {**summary(calls), "amd_calls": amd, "other_calls": len(calls) - amd,
            "other_hosts": list(dict.fromkeys(_host(c) for c in calls if c.get("host") != TOKEN_FACTORY_HOST)),
            "amd_share": amd / len(calls) if calls else None, "per_model": per_model}


def tokens_text(s: dict) -> str:
    """Prompt / completion tokens summed over the answered calls whose server reported usage; n/a when none did."""
    if not s["with_usage"]:
        return "n/a"
    return f"{s['prompt_tokens']} / {s['completion_tokens']}" + (
        "" if s["with_usage"] == s["ok"] else f" (usage on {s['with_usage']} of {s['ok']} answered calls)")


def _seconds(x) -> str:
    return "n/a" if x is None else f"{x:.2f} s"


def endpoint_share(s: dict) -> str:
    """Where this session's calls went, by the host each call was sent to."""
    if not s["calls"]:
        return "No model call yet in this session."
    if not s["amd_calls"]:
        return (f"No call went to the AMD Token Factory endpoint ({TOKEN_FACTORY_HOST}): {_plural(s['calls'], 'call')} to "
                f"{', '.join(s['other_hosts'])}.")
    text = (f"{s['amd_calls']} of {_plural(s['calls'], 'call')} ({s['amd_share']:.0%}) went to the AMD Token Factory "
            f"endpoint ({TOKEN_FACTORY_HOST})")
    return text + (f"; {s['other_calls']} to other hosts: {', '.join(s['other_hosts'])}." if s["other_calls"] else ".")


def model_rows(s: dict) -> list:
    """One display row per model called this session."""
    return [{"Model": m["model"], "Role (stage of its calls)": ", ".join(m["roles"]), "Calls": str(m["calls"]),
             "Answered": str(m["ok"]),
             "Endpoint host": ", ".join(h + (" (AMD Token Factory)" if h == TOKEN_FACTORY_HOST else "") for h in m["hosts"]),
             "p50 latency": _seconds(m["median_latency_s"]), "Tokens (prompt / completion)": tokens_text(m)}
            for m in s["per_model"]]


def configured_roles(status: dict, s: dict) -> list:
    """Configured models with no call yet this session, so with no stage to read: the role the family timeline gives
    the variable that names them (CARERELAY_LLM_MODEL: facts and answers, and photos too when CARERELAY_PHOTO_MODEL is
    not set; CARERELAY_PHOTO_MODEL: photos), labelled as a configured role."""
    called = {m["model"] for m in s["per_model"]}
    roles: dict = {}
    for model, role in ((status["model"], "fact extraction, question answers"
                         + ("" if status["photo_model"] else ", photo reading")), (status["photo_model"], "photo reading")):
        if model and model not in called:
            roles.setdefault(model, []).append(role)
    return [f"{m}: {', '.join(r)} (configured role; not called yet this session)" for m, r in roles.items()]


def _cell(v: str) -> str:
    return str(v).replace("|", "/").replace("\n", " ")


def markdown_table(rows: list) -> str:
    if not rows:
        return ""
    head = list(rows[0])
    return "\n".join(["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
                     + ["| " + " | ".join(_cell(r[h]) for h in head) + " |" for r in rows])


def _status(st, status: dict) -> None:
    (st.success if status["token_factory"] else st.info if not status["configured"] else st.warning)(status["label"])


def render_page(st, recorder, state, env=None) -> None:
    status = endpoint_status(env)
    st.title("AMD Runtime")
    _status(st, status)
    models = ", ".join(f"{k}: {v}" for k, v in (("text model", status["model"]), ("photo model", status["photo_model"])) if v)
    st.caption((f"Configured endpoint host: {status['host']}. " if status["host"] else "")
               + (f"Configured {models}. " if models else "")
               + "The provider's GPU is not visible to this client, so no GPU, precision or cost is claimed here.")
    calls = recorder.calls()
    s = session_summary(calls)
    st.subheader("This session")
    a, b, c, d, e = st.columns(5)
    a.metric("Model calls this session", s["calls"])
    b.metric("To the AMD Token Factory endpoint", f"{s['amd_calls']} of {s['calls']}"
             + (f" ({s['amd_share']:.0%})" if s["calls"] else ""),
             help=f"Calls sent to {TOKEN_FACTORY_HOST}, by the host each call was sent to.")
    c.metric("Answered", s["ok"])
    d.metric("Median latency (p50)", _seconds(s["median_latency_s"]))
    e.metric("Tokens (prompt / completion)", f"{s['prompt_tokens']} / {s['completion_tokens']}" if s["with_usage"] else "n/a",
             help=f"Summed over the {s['with_usage']} answered calls whose server reported usage; never estimated.")
    st.caption(endpoint_share(s) + (f" Counted over the newest {len(calls)} of {recorder.total} calls."
                                    if recorder.total > len(calls) else ""))
    if calls:
        st.markdown(markdown_table(model_rows(s)))
        st.caption("Role: the stages of the model's own calls this session, read from each call (the reply schema it "
                   "asked for, or that it carried a photo). p50 latency and tokens cover its answered calls; tokens are "
                   "the server's usage field, n/a when it sent none.")
    configured = configured_roles(status, s)
    if configured:
        st.caption("Configured, no call yet: " + "; ".join(configured) + ".")
    if not calls:
        st.info("No model call yet in this browser session. Use the family timeline (ask a question, add a typed update, "
                "or read a photo) with a live model configured, then come back here.")
    else:
        st.subheader("Each call, newest first")
        if recorder.total > len(calls):
            st.caption(f"Showing the newest {len(calls)} of {recorder.total} calls.")
        st.markdown(markdown_table(call_rows(calls, output_checks(state))))
    st.caption("Latency is the round trip of the try that succeeded (failed tries and the waits between them are left "
               "out; a retry wait is shown beside it). Token counts are the server's usage field, n/a when it sent none. "
               "Output check is what the backend did with the reply: the model proposes, the backend decides. Fact "
               "extraction: every fact must quote the update word for word, or it is rejected; question answers: the "
               "model only chooses sentence ids, which the answer check verifies. Only this session's calls are listed; "
               "prompts, replies, images and keys are not recorded.")


def sidebar_panel(st, recorder, runtime_page=None, env=None) -> None:
    status = endpoint_status(env)
    calls = recorder.calls()
    with st.expander(f"AMD Runtime · {_plural(len(calls), 'model call')}", expanded=False):
        st.caption(status["label"])
        if calls:
            s = session_summary(calls)
            st.caption(endpoint_share(s))
            st.caption(f"Tokens (prompt / completion) {tokens_text(s)} · p50 latency {_seconds(s['median_latency_s'])}")
            for m in s["per_model"]:
                st.caption(f"{m['model']}: {', '.join(m['roles'])} · {_plural(m['calls'], 'call')}")
            last = calls[-1]
            how = (f"{last['latency_s']:.2f} s" if last.get("ok") and isinstance(last.get("latency_s"), (int, float))
                   else f"error: {last.get('error') or 'unknown'}")
            st.caption(f"Last: {stage_label(last)} · {last.get('model') or 'n/a'} · {last.get('host') or 'n/a'} · {how} · "
                       f"tokens {_n(last.get('prompt_tokens'))} / {_n(last.get('completion_tokens'))}")
        if runtime_page is not None:
            st.page_link(runtime_page, label="Open the AMD Runtime page")
