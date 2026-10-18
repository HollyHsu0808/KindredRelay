#!/usr/bin/env python3
"""Extract care instructions from a transcript_result JSON (Whisper output or the PriMock human fixture).

Every proposal must quote one transcript segment verbatim; proposals whose quote is not in the cited segment are
rejected (grounding check). Output: instructions + rejected + LLM metadata. These are DRAFTS for a caregiver to
check against the audio (product plan: numbers, negations and conditions are always human-checked).

Usage:
  python extract_instructions.py --transcript ../integration_samples/primock57/transcript_result.doctor.fixture.json --out /tmp/ins.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from case_agent import CaseAgent  # noqa: E402
from llm_client import make_client  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--transcript", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--backend", default=None)
    ap.add_argument("--max-segments", type=int, default=120, help="cap the prompt size (long consultations)")
    args = ap.parse_args()
    tr = json.loads(args.transcript.read_text(encoding="utf-8"))
    segs = [{"segment_id": g["segment_id"], "text": g.get("text_plain") or g["text"]} for g in tr["segments"]][: args.max_segments]
    llm = make_client(args.backend)
    agent = CaseAgent(store=None, llm=llm)
    res = agent.extract_instructions(segs)
    out = {"input_id": tr.get("input_id"), "transcript_source": tr.get("transcript_source"), "source_revision": tr.get("source_revision"),
           "segments_used": len(segs), "segments_total": len(tr["segments"]), "llm": llm.describe(), **res,
           "notice": "draft instructions; a person checks each against the audio before they enter the case"}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"out": str(args.out), "grounded": len(res["instructions"]), "rejected": len(res["rejected"]),
                      "json_mode": res["json_mode"], "latency_s": res["latency_s"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
