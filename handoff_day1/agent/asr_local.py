"""Speech-to-text on this machine for the family timeline's "Add a recording": Whisper (openai-whisper, MIT licence)
through scripts/asr_whisper.py's WhisperASR, the same code as the PriMock57 evaluation. Needs openai-whisper and torch
(model/requirements-asr.txt) and the ffmpeg program; the Docker image has none of them, so there the page asks the family
to type what was said. The model (CARERELAY_ASR_MODEL, default base.en: about 140 MB, quick on a laptop CPU; small.en
is more accurate and slower) downloads on first use. scripts/check_whisper.py tries it on a sample recording.
"""
from __future__ import annotations

import importlib.util
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_models: dict[str, object] = {}


def missing() -> list[str]:
    """What this machine lacks to write out a recording; empty when it is ready."""
    def has(module: str) -> bool:
        try:
            return importlib.util.find_spec(module) is not None
        except (ValueError, ImportError):   # already imported without a spec: present
            return module in sys.modules
    out = [name for module, name in (("whisper", "openai-whisper"), ("torch", "torch")) if not has(module)]
    if shutil.which("ffmpeg") is None:
        out.append("ffmpeg")
    return out


def model(name: str):
    """One Whisper model per process (loading takes seconds), shared by every page session."""
    if name not in _models:
        if str(ROOT / "scripts") not in sys.path:
            sys.path.insert(0, str(ROOT / "scripts"))
        from asr_whisper import WhisperASR
        _models[name] = WhisperASR(name)
    return _models[name]


def transcriber(name: str | None = None):
    """transcribe(audio bytes, file suffix) -> {"text" (one line per Whisper segment), "model", "latency_s",
    "needs_check" (the kinds of words a person must check against the audio: numbers, times, negations, conditions)}."""
    name = name or os.environ.get("CARERELAY_ASR_MODEL", "base.en")

    def transcribe(data: bytes, suffix: str = ".wav") -> dict:
        t0 = time.perf_counter()
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / f"recording{suffix or '.wav'}"
            path.write_bytes(data)
            out = model(name).transcribe(path, "family-timeline:recording", "clinician")
        # One line per recording on stderr, which the host shows in its log: enough to tell a silent or
        # undecodable clip from a real one. No word of what was said is logged, only counts.
        segs = out["segments"]
        print("[asr] bytes=%d suffix=%s duration_s=%s segments=%d chars=%d no_speech_prob=%s avg_logprob=%s" % (
            len(data), suffix or ".wav", out["quality"].get("duration_s"), len(segs),
            sum(len(s["text"]) for s in segs),
            max((s.get("no_speech_prob", 0.0) for s in segs), default=None),
            min((s.get("avg_logprob", 0.0) for s in segs), default=None)), file=sys.stderr, flush=True)
        return {"text": "\n".join(s["text"] for s in out["segments"]), "model": f"Whisper {name}",
                "latency_s": round(time.perf_counter() - t0, 2), "needs_check": out["quality"]["needs_human_check"]}
    transcribe.model_name = name
    return transcribe
