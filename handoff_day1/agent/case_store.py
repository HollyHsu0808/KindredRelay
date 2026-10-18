"""Reference case state for the CareRelay Case Agent (deterministic backend logic, no LLM).

Data chain (care_cases.md §0): case -> source -> instruction -> task / sheet_section / handover_item.
The LLM never edits this state directly. It PROPOSES (a reply, a pending question, a new item version); this store
validates the proposal and applies it with the backend rules:
  - instructions are never changed by a conversation (only a verified source revision can update them);
  - a transcript correction creates a new transcript revision, never a new instruction;
  - impact analysis is segment-level: only items citing the changed segment become stale;
  - new versions are pending_review; old versions are superseded with superseded_by; history is kept;
  - case_version is bumped once, after all new versions exist.
Leo owns the production storage and API; this module defines the same semantics for tests and the evaluation.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path


def content_hash(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


class CaseStore:
    def __init__(self, scenario: dict):
        self.scenario_id = scenario.get("scenario_id")
        self.case_id = scenario["case_id"]
        self.case_version = 1
        self.sources: dict[tuple[str, str], dict] = {}  # (source_id, revision) -> source
        for s in scenario["sources"]:
            segs = s.get("segments") or [{"segment_id": x["segment_id"], "text": x["audio_says"], "audio_span": x.get("audio_span")}
                                         for x in s.get("segments_spoken", [])]
            self.sources[(s["source_id"], s["revision"])] = {**{k: v for k, v in s.items() if k not in ("segments", "segments_spoken")},
                                                             "segments": {g["segment_id"]: dict(g) for g in segs}}
        self.instructions = {i["instruction_id"]: copy.deepcopy(i) for i in scenario["instructions"]}
        self.items: dict[str, list[dict]] = {}  # item_id -> versions (oldest first)
        for it in scenario.get("items_before", []):
            self.items.setdefault(it["item_id"], []).append(copy.deepcopy(it))
        self.pending: list[dict] = []
        self.teach_back: list[dict] = []
        self.corrections: list[dict] = []
        self.audit: list[dict] = []

    @classmethod
    def from_file(cls, path: Path) -> "CaseStore":
        return cls(json.loads(Path(path).read_text()))

    # ---------------------------------------------------------------- reads (agent tools)
    def latest_revision(self, source_id: str) -> str | None:
        revs = sorted((r for (sid, r) in self.sources if sid == source_id), key=lambda r: int(r.lstrip("r") or 0))
        return revs[-1] if revs else None

    def segment_text(self, source_id: str, revision: str, segment_id: str) -> str | None:
        s = self.sources.get((source_id, revision))
        return s["segments"].get(segment_id, {}).get("text") if s else None

    def latest(self, item_id: str) -> dict:
        return self.items[item_id][-1]

    def active_instructions(self) -> list[dict]:
        return [i for i in self.instructions.values() if i.get("status") == "active"]

    def instruction_context(self) -> list[dict]:
        """Each active instruction with the verbatim text of what it cites (what the agent may quote)."""
        out = []
        for ins in self.active_instructions():
            cites = []
            for c in ins["cites"]:
                src = self.sources.get((c["source_id"], c["revision"]), {})
                cites.append({**c, "source_type": src.get("source_type"), "text": self.segment_text(c["source_id"], c["revision"], c["segment_id"])})
            out.append({k: ins.get(k) for k in ("instruction_id", "action", "condition", "time", "derivation_status")} | {"cites": cites})
        return out

    def correction_context(self) -> list[dict]:
        return [dict(c) for c in self.corrections]

    def recording_says(self, transcript_source_id: str, segment_id: str) -> str | None:
        """For a transcript, what the authoritative recording it transcribes says at the same segment."""
        tx = next((s for (sid, _), s in self.sources.items() if sid == transcript_source_id), None)
        if not tx or not tx.get("transcribes"):
            return None
        rec_rev = self.latest_revision(tx["transcribes"])
        return self.segment_text(tx["transcribes"], rec_rev, segment_id) if rec_rev else None

    def current_source_texts(self) -> list[str]:
        """Segment texts of the LATEST revision of every source: what a reply may quote. A superseded revision
        (e.g. the wrong transcript r1 after a correction) is history, not a source to repeat."""
        return [g["text"] for (sid, rev), src in self.sources.items() if rev == self.latest_revision(sid)
                for g in src["segments"].values() if g.get("text")]

    def cite_is_valid(self, c: dict) -> bool:
        """A citation must point at an existing segment of the source's latest revision."""
        if not isinstance(c, dict) or not all(isinstance(c.get(k, ""), str) for k in ("source_id", "revision", "segment_id")):
            return False
        if c.get("revision") != self.latest_revision(c.get("source_id", "")):
            return False
        return self.segment_text(c.get("source_id", ""), c.get("revision", ""), c.get("segment_id", "")) is not None or \
            ((c.get("source_id"), c.get("revision")) in self.sources and not c.get("segment_id"))

    # ---------------------------------------------------------------- all-or-nothing updates
    def snapshot(self) -> dict:
        return copy.deepcopy(self.__dict__)

    def restore(self, snap: dict) -> None:
        """Undo a multi-step update that failed halfway (e.g. the LLM failed during regeneration)."""
        self.__dict__.clear()
        self.__dict__.update(copy.deepcopy(snap))

    def snapshot_hashes(self) -> dict:
        """Content hash + status of every source, instruction and latest item (for 'unchanged' checks)."""
        h = {f"{sid}@{rev}": content_hash(s) for (sid, rev), s in self.sources.items()}
        h.update({iid: content_hash(i) for iid, i in self.instructions.items()})
        h.update({iid: content_hash(v[-1]) for iid, v in self.items.items()})
        return h

    # ---------------------------------------------------------------- writes (validated proposals)
    def add_pending(self, type_: str, text: str, cites: list[dict], owner: str = "care team (to be assigned)") -> dict:
        assert type_ in ("needs_clinical_confirmation", "needs_transcript_check", "conflict"), type_
        key = "question" if type_ != "conflict" else "detail"
        dup = next((q for q in self.pending if q["status"] == "open" and q["type"] == type_ and q.get(key) == text), None)
        if dup:  # the same open question asked again: do not file it twice
            return dup
        p = {"pending_id": f"pend-{len(self.pending) + 1:03d}", "type": type_,
             ("question" if type_ != "conflict" else "detail"): text, "cites": cites, "owner": owner, "status": "open"}
        self.pending.append(p)
        self.audit.append({"op": "add_pending", "pending_id": p["pending_id"]})
        return p

    def propose_version(self, item_id: str, content: str, cites: list[dict] | None = None, reason: str = "") -> dict:
        prev = self.latest(item_id)
        if prev.get("review_status") == "pending_review":  # an unreviewed proposal is replaced, not stacked
            prev["review_status"] = "superseded"
            prev["superseded_by"] = prev.get("version", 1) + 1
        v = {**{k: prev[k] for k in ("item_id", "kind") if k in prev}, "version": prev.get("version", 1) + 1,
             "review_status": "pending_review", "content": content, "cites": cites if cites is not None else prev.get("cites", []),
             "previous_version": prev.get("version", 1), "reason": reason}
        self.items[item_id].append(v)
        self.audit.append({"op": "propose_version", "item_id": item_id, "version": v["version"]})
        return v

    def record_teach_back(self, instruction_id: str, question: str, response_verbatim: str, actor: str) -> dict:
        rec = {"instruction_id": instruction_id, "question": question, "response_verbatim": response_verbatim,
               "actor": actor, "auto_scored": False}
        self.teach_back.append(rec)
        self.audit.append({"op": "teach_back", "instruction_id": instruction_id})
        return rec

    def apply_transcript_correction(self, corr: dict) -> dict:
        """Create the corrected transcript revision and run segment-level impact analysis. No new instruction."""
        self.validate_correction(corr)
        sid, base, seg = corr["source_id"], corr["base_revision"], corr["segment_id"]
        old = self.sources[(sid, base)]
        before = old["segments"][seg]["text"]
        new_rev = f"r{int(base.lstrip('r')) + 1}"
        new = copy.deepcopy(old)
        new["revision"] = new_rev
        new["review_status"] = "transcript_verified_by_caregiver"
        new["segments"][seg]["text"] = before.replace(corr["from"], corr["to"])
        return self._apply_correction(corr, sid, seg, old, new, new_rev, before)

    def validate_correction(self, corr: dict) -> None:
        """Raise ValueError if this correction cannot be applied (checked before anything changes)."""
        need = ("source_id", "base_revision", "segment_id", "from", "to")
        if not isinstance(corr, dict) or not all(isinstance(corr.get(k), str) for k in need):
            raise ValueError(f"a correction needs string fields {list(need)}")
        sid, base, seg = corr["source_id"], corr["base_revision"], corr["segment_id"]
        old = self.sources.get((sid, base))
        if old is None:
            raise ValueError(f"unknown source {sid} revision {base}")
        if old.get("source_type") != "transcript":
            raise ValueError(f"{sid} is a {old.get('source_type')}, not a transcript: only transcripts can be corrected")
        if base != self.latest_revision(sid):
            raise ValueError(f"base_revision {base} is not the latest revision of {sid} ({self.latest_revision(sid)})")
        if not isinstance(corr.get("from"), str) or not isinstance(corr.get("to"), str) or not corr["from"].strip() \
                or corr["from"] == corr["to"] or len(corr["from"]) > 200 or len(corr["to"]) > 200:
            raise ValueError("'from' and 'to' must be different non-empty strings (at most 200 characters)")
        if seg not in old["segments"]:
            raise ValueError(f"unknown segment_id {seg}")
        if corr["from"] not in old["segments"][seg]["text"]:
            raise ValueError(f"'{corr['from']}' not found in {sid} {base} {seg}")

    def _apply_correction(self, corr, sid, seg, old, new, new_rev, before) -> dict:
        self.sources[(sid, new_rev)] = new
        record = {**corr, "new_revision": new_rev, "creates_new_instruction": False, "segment_before": before,
                  "segment_after": new["segments"][seg]["text"]}
        self.corrections.append(record)
        changed = {s for s in new["segments"] if new["segments"][s]["text"] != old["segments"][s]["text"]}
        impact = []
        for iid, versions in self.items.items():
            cur = versions[-1]
            if cur.get("review_status") == "rejected":   # withdrawn: no current content, and a correction never brings it back
                continue
            if any(c["source_id"] == sid and c["segment_id"] in changed for c in cur.get("cites", [])):
                if cur.get("review_status") == "approved":
                    cur["approved_before"] = True   # only a version a person approved may ever be restored by a rejection
                cur["review_status"] = "stale"
                impact.append(iid)
        live = {i: ins for i, ins in self.instructions.items() if ins.get("status", "active") == "active"}   # a withdrawn one stays withdrawn
        affected_instructions = [i for i, ins in live.items()
                                 if any(c["source_id"] == sid and c["segment_id"] in changed for c in ins["cites"])]
        unchanged_seg_citers = [i for i, ins in live.items()
                                if any(c["source_id"] == sid and c["segment_id"] not in changed for c in ins["cites"])]
        self.audit.append({"op": "transcript_correction", "source_id": sid, "new_revision": new_rev, "impact_set": impact})
        return {"new_revision": new_rev, "changed_segments": sorted(changed), "impact_set": impact,
                "affected_instructions": affected_instructions, "repointable_instructions": unchanged_seg_citers,
                "record": record}

    def supersede_with(self, item_id: str, content: str, new_rev: str, source_id: str) -> dict:
        """Replace a stale item with a regenerated version citing the new revision."""
        old = self.latest(item_id)
        cites = [{**c, "revision": new_rev} if c["source_id"] == source_id else c for c in old.get("cites", [])]
        v = self.propose_version(item_id, content, cites, reason="regenerated after transcript correction")
        old["review_status"] = "superseded"
        old["superseded_by"] = v["version"]
        return v

    def update_instruction_from_revision(self, instruction_id: str, new_time: str | None, new_rev: str, source_id: str) -> dict:
        ins = self.instructions[instruction_id]
        if ins.get("derivation_status") != "pending_review" or not ins.get("previous"):
            # the last APPROVED state, kept while changes stack up unreviewed; a never-approved instruction's state is
            # marked was_approved False (a rejection withdraws it rather than presenting that state as approved)
            # (time, condition, action and cites: a rejection restores all of them, never a condition or an action a later
            # change brought)
            ins["previous"] = {**{k: ins.get(k) for k in ("time", "condition", "action", "cites")},
                               "was_approved": ins.get("derivation_status") not in ("pending_review", "rejected")}
        if new_time is not None:
            ins["time"] = new_time
        ins["cites"] = [{**c, "revision": new_rev} if c["source_id"] == source_id else c for c in ins["cites"]]
        ins["derivation_status"] = "pending_review"
        ins["last_change"] = {"kind": "transcript_correction", "source_id": source_id, "revision": new_rev}  # what the Q&A looks at
        self.audit.append({"op": "update_instruction", "instruction_id": instruction_id})
        return ins

    def bump_case_version(self) -> int:
        self.case_version += 1
        self.audit.append({"op": "case_version", "value": self.case_version})
        return self.case_version

    def approve(self, ids: list[str]) -> None:
        for i in ids:
            if i in self.items:
                self.latest(i)["review_status"] = "approved"
            elif i in self.instructions:
                self.instructions[i]["derivation_status"] = "approved"
        self.audit.append({"op": "approve", "ids": ids})

    def export_pdf_record(self, pdf_id: str) -> dict:
        """What a PDF export would contain (the real PDF is rendered by the backend from a fixed template). An export
        is stored under its own id: it never becomes a version of a task, note or sheet section."""
        if not isinstance(pdf_id, str) or not pdf_id.startswith("pdf-"):
            raise ValueError("pdf_id must start with 'pdf-'")
        if pdf_id in self.items and self.latest(pdf_id).get("kind") != "exported_pdf":
            raise ValueError(f"{pdf_id} is an item of this case, not an export id")
        body = [self.latest(i)["content"] for i in self.items if self.latest(i).get("kind") in ("handover_item", "sheet_section", "task")
                and self.latest(i).get("review_status") == "approved"]
        rec = {"item_id": pdf_id, "kind": "exported_pdf", "case_version": self.case_version, "content": "\n".join(body)}
        self.items.setdefault(pdf_id, []).append(rec)
        return rec

    def pending_review_count(self) -> int:
        n = sum(1 for v in self.items.values() if v[-1].get("review_status") == "pending_review")
        return n + sum(1 for i in self.instructions.values() if i.get("derivation_status") == "pending_review")
