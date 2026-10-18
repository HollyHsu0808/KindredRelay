"""Versioned command journal for Episode. Replay is local and never calls a model.

The journal is the persistence boundary; projections are deliberately rebuilt rather
than deserialising object graphs whose identity used to carry QA state.
"""
from __future__ import annotations

import copy
import hashlib
import json

JOURNAL_VERSION = 1
PROJECTION_VERSION = "episode-revision-v1"


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


class RevisionConflict(ValueError):
    """The source changed after the caller opened it."""


class EpisodeJournal:
    @property
    def events(self):
        return copy.deepcopy(self._events)

    @property
    def state_revision(self):
        return digest({"version": PROJECTION_VERSION, "scenario": self.scenario, "events": self._events})

    def source_revision(self, update_id):
        if update_id not in self._sources:
            raise ValueError(f"unknown update {update_id}")
        return self._sources[update_id]["revision"]

    def source_history(self, update_id):
        return [copy.deepcopy(e) for e in self._events
                if e.get("update_id") == update_id and e["op"] in ("add", "revise", "delete")]

    def to_snapshot(self):
        payload = {"format": JOURNAL_VERSION, "projection": PROJECTION_VERSION,
                   "scenario": copy.deepcopy(self.scenario), "events": self.events}
        return {**payload, "sha256": digest(payload)}

    @classmethod
    def from_snapshot(cls, snapshot):
        payload = {k: copy.deepcopy(v) for k, v in snapshot.items() if k != "sha256"}
        if payload.get("format") != JOURNAL_VERSION or payload.get("projection") != PROJECTION_VERSION:
            raise ValueError("unsupported Episode snapshot version")
        if snapshot.get("sha256") != digest(payload):
            raise ValueError("Episode snapshot checksum mismatch")
        obj = cls(payload["scenario"])
        obj._rebuild(payload["events"])
        return obj

    def _idempotent(self, request_id, request):
        if request_id is None:
            return None
        if not isinstance(request_id, str) or not request_id.strip():
            raise ValueError("request_id must be nonempty text")
        for event in self._events:
            if event.get("request_id") == request_id:
                if event["request_sha256"] != digest(request):
                    raise RevisionConflict("request_id was already used for a different command")
                return event
        return None

    def _prepare_source(self, update, facts, extractor, checker, revision, method=None):
        update = copy.deepcopy(update)
        update["source_revision"] = revision
        update["hospital_timezone"] = self.patient.get("timezone") or "UTC"
        # Validate before invoking external extraction or verification.
        from episode import CARE_TEAM_KINDS, grounding_problem, norm, parse_when, source_authority
        import datetime as dt
        if not isinstance(update.get("update_id"), str) or not update["update_id"].strip():
            raise ValueError("update_id must be nonempty text")
        if update.get("kind") not in (*CARE_TEAM_KINDS, "note"):
            raise ValueError("kind must be recording, photo or note")
        source_authority(update)   # reject an invalid speaker type before extraction or verification
        at = parse_when(update.get("at"))
        if not isinstance(at, dt.datetime) or at.tzinfo is None:
            raise ValueError("at must be an ISO date-time with its UTC offset")
        if not isinstance(update.get("text", ""), str):
            raise ValueError("text must be text")
        method = method or ("llm" if facts is None and extractor is not None else "replay")
        if facts is None:
            facts = extractor(copy.deepcopy(update), copy.deepcopy(self)) if extractor is not None else update.get("recorded_extraction", [])
        proposals = copy.deepcopy(facts if isinstance(facts, list) else [])
        checks = {}
        if checker is not None:
            for i, raw in enumerate(proposals):
                fact = self._keep_negation(self._tidy(raw))
                if grounding_problem(fact, update.get("text", ""), update["at"]):
                    continue
                fact = self._anchor(fact)
                fact["fact_id"] = f"{update['update_id']}@{revision}:f{i + 1}"
                result = checker(copy.deepcopy(update), copy.deepcopy(fact))
                if not isinstance(result, dict) or result.get("mode") not in ("shadow", "gate"):
                    raise ValueError("evidence checker returned an invalid result")
                from evidence_gate import bind_check
                checks[fact["fact_id"]] = bind_check(update, fact, result)
        # Freeze proposals and verification decisions, including rejected proposals.
        return {"update": update, "facts": proposals, "checks": checks, "method": method}

    def add_update(self, update, facts=None, extractor=None, evidence_checker=None, request_id=None):
        request = {"op": "add", "update": update, "facts": facts}
        duplicate = self._idempotent(request_id, request)
        if duplicate:
            return copy.deepcopy(duplicate["result"])
        uid = update.get("update_id")
        if uid in self._sources:
            raise ValueError(f"update {uid} was already added")
        prepared = self._prepare_source(update, facts, extractor, evidence_checker, 1)
        return self._commit({"op": "add", "update_id": uid, "revision": 1, **prepared}, request_id, request)

    def revise_update(self, update_id, replacement, *, expected_revision, request_id,
                      facts=None, extractor=None, evidence_checker=None):
        request = {"op": "revise", "update_id": update_id, "replacement": replacement,
                   "expected_revision": expected_revision, "facts": facts}
        duplicate = self._idempotent(request_id, request)
        if duplicate:
            return copy.deepcopy(duplicate["result"])
        source = self._require_source(update_id, expected_revision)
        if "update_id" in replacement and replacement["update_id"] != update_id:
            raise ValueError("a correction cannot change update_id")
        update = {**source["update"], **copy.deepcopy(replacement), "update_id": update_id}
        changed = any(update.get(k) != source["update"].get(k)
                      for k in ("text", "at", "kind", "speaker", "speaker_type", "photo_of", "reading"))
        if changed and facts is None and extractor is None:
            raise ValueError("a changed source requires replacement facts or an extractor")
        if not changed and facts is None and extractor is None:
            facts = source["facts"]
        prepared = self._prepare_source(update, facts, extractor, evidence_checker, source["revision"] + 1)
        return self._commit({"op": "revise", "update_id": update_id, "revision": source["revision"] + 1,
                             **prepared}, request_id, request)

    def delete_update(self, update_id, *, expected_revision, request_id):
        request = {"op": "delete", "update_id": update_id, "expected_revision": expected_revision}
        duplicate = self._idempotent(request_id, request)
        if duplicate:
            return copy.deepcopy(duplicate["result"])
        source = self._require_source(update_id, expected_revision)
        return self._commit({"op": "delete", "update_id": update_id, "revision": source["revision"] + 1},
                            request_id, request)

    def _require_source(self, uid, expected_revision):
        source = self._sources.get(uid)
        if source is None or source.get("deleted"):
            raise ValueError(f"unknown active update {uid}")
        if type(expected_revision) is not int or expected_revision != source["revision"]:
            raise RevisionConflict(f"source {uid} changed; reopen it before saving")
        return source

    def add_question(self, text, member_id, asked_seq=None):
        probe = copy.deepcopy(self)
        q, joined = probe._add_question(text, member_id, asked_seq)
        result = self._commit({"op": "question", "text": text, "member_id": member_id,
                               "asked_seq": asked_seq, "qid": q["qid"], "decision": joined,
                               "question_state": copy.deepcopy(q)})
        return next(q for q in self.questions if q["qid"] == result["qid"]), joined

    def _answer_dependencies(self, qid, update_id):
        pair = next((p for p in self.two_answers() if p["qid"] == qid), None)
        uids = [a["update_id"] for a in pair["answers"]] if pair else ([update_id] if update_id else [])
        return {uid: self._sources[uid]["revision"] for uid in uids if uid in self._sources}

    def set_answered(self, qid, answered=True, update_id=None, by=None):
        q = next((q for q in self.questions if q["qid"] == qid), None)
        if q is None:
            raise ValueError(f"unknown question {qid}")
        self._commit({"op": "answered", "qid": qid, "answered": answered, "update_id": update_id, "by": by,
                      "dependencies": self._answer_dependencies(qid, update_id), "question": copy.deepcopy(q)})
        return next(q for q in self.questions if q["qid"] == qid)

    def confirm_answer(self, qid, update_id, by):
        q = next((q for q in self.questions if q["qid"] == qid), None)
        if q is None:
            raise ValueError(f"unknown question {qid}")
        self._commit({"op": "confirm", "qid": qid, "update_id": update_id, "by": by,
                      "dependencies": self._answer_dependencies(qid, update_id), "question": copy.deepcopy(q)})
        return next(q for q in self.questions if q["qid"] == qid)

    def mark_read(self, member_id):
        self._commit({"op": "read", "member_id": member_id, "seen": self.seq, "seen_at": self.latest_at()})

    def _commit(self, event, request_id=None, request=None):
        event = copy.deepcopy(event)
        event["event_id"] = len(self._events) + 1
        event["source_seq"] = self.seq + (event["op"] in ("add", "revise", "delete"))
        if request_id is not None:
            event.update(request_id=request_id, request_sha256=digest(request))
        candidate = type(self)(self.scenario)
        candidate._rebuild([*self._events, event])
        if event["op"] in ("add", "revise"):
            result = candidate.render(next(e for e in candidate.entries if e["update_id"] == event["update_id"]))
        elif event["op"] == "delete":
            result = {"update_id": event["update_id"], "source_revision": event["revision"], "deleted": True}
        elif event["op"] == "question":
            result = copy.deepcopy(next(q for q in candidate.questions if q["qid"] == event["qid"]))
        else:
            result = None
        if request_id is not None:
            candidate._events[-1]["result"] = copy.deepcopy(result)
        # Preserve existing question references used by the UI and legacy callers.
        refs = {q["qid"]: q for q in self.questions}
        for i, q in enumerate(candidate.questions):
            if q["qid"] in refs:
                old = refs[q["qid"]]
                old.clear(); old.update(q)
                candidate.questions[i] = old
        self.__dict__.clear(); self.__dict__.update(candidate.__dict__)
        return result

    def _rebuild(self, events):
        events = copy.deepcopy(events)
        sources = {}
        for i, e in enumerate(events, 1):
            if e.get("event_id") != i or e.get("op") not in ("add", "revise", "delete", "question", "answered", "confirm", "read"):
                raise ValueError("invalid Episode command journal")
            if e["op"] in ("add", "revise", "delete"):
                uid = e["update_id"]
                old = sources.get(uid)
                expected = 1 if old is None else old["revision"] + 1
                if e["revision"] != expected or (e["op"] == "add") != (old is None) or (old and old.get("deleted")):
                    raise ValueError("invalid source revision chain")
                sources[uid] = {**e, "deleted": e["op"] == "delete"}
        self._sources = sources
        for e in events:
            op = e["op"]
            if op == "add":
                source = sources[e["update_id"]]
                if not source["deleted"]:
                    self.seq = e["source_seq"] - 1
                    self._add_update(copy.deepcopy(source["update"]), facts=copy.deepcopy(source["facts"]),
                                     evidence_results=source["checks"], method=source["method"])
                    self.entries[-1]["seq"] = source["source_seq"]
            elif op == "question":
                self.seq = e["source_seq"]
                if e["member_id"] not in self.members:
                    raise ValueError("unknown question member")
                q = next((q for q in self.questions if q["qid"] == e["qid"]), None)
                if q is not None:
                    if e["member_id"] not in q["askers"]:
                        q["askers"].append(e["member_id"])
                else:
                    # Replay the recorded creation/join decision; running live
                    # deduplication again could merge q2 into a reopened q1.
                    q = copy.deepcopy(e["question_state"])
                    q.update(status="open", answered_by=None, marked_by=None)
                    q.pop("confirmed", None)
                    self.questions.append(q)
                    if e["qid"].startswith("auto-"):
                        q["invalidation_reason"] = "The sources changed. Please check this question again."
            elif op in ("answered", "confirm"):
                stale = any(uid not in sources or sources[uid]["deleted"] or sources[uid]["revision"] != rev
                            for uid, rev in e["dependencies"].items())
                q = next((q for q in self.questions if q["qid"] == e["qid"]), None)
                if stale:
                    if q is None:
                        q = copy.deepcopy(e["question"]); self.questions.append(q)
                    q.update(status="open", answered_by=None, marked_by=None,
                             invalidation_reason="The source was updated or removed. Please check the answer again.")
                    q.pop("confirmed", None)
                    q.pop("answered_revision", None)
                elif op == "confirm":
                    self._confirm_answer(e["qid"], e["update_id"], e["by"])
                else:
                    self._set_answered(e["qid"], e["answered"], e["update_id"], e["by"])
                if q is not None and not stale:
                    q["answered_revision"] = copy.deepcopy(e["dependencies"])
            elif op == "read":
                self._mark_read(e["member_id"])
                self.seen[e["member_id"]] = e["seen"]
                self.seen_at[e["member_id"]] = e["seen_at"]
        self.seq = max((e["source_seq"] for e in events), default=0)
        self._events = events
