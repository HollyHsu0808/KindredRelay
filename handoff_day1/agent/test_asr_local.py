#!/usr/bin/env python3
"""The family timeline's speech-to-text adapter (agent/asr_local.py) against scripts/asr_whisper.py's real WhisperASR,
with small stand-ins for the openai-whisper and torch modules (the real ones are not installed where the tests run):
the recording is written to a file with its suffix, decoded, transcribed, and comes back one line per segment with the
kinds of words a person must check. Stdlib only:
  python agent/test_asr_local.py
"""
from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
SAMPLE = HERE.parent / "integration_samples" / "primock57" / "day1_consultation01_seg087_doctor.wav"


def stand_ins(calls: list) -> dict:
    whisper = types.ModuleType("whisper")
    whisper.__version__ = "stand-in"
    whisper.audio = types.SimpleNamespace(SAMPLE_RATE=16000)

    def load_audio(path):
        calls.append(("load_audio", Path(path).suffix, Path(path).read_bytes()[:4]))
        return [0.0] * 16000 * 9

    class Model:
        def transcribe(self, audio, **kw):
            calls.append(("transcribe", len(audio), kw.get("language"), kw.get("condition_on_previous_text")))
            return {"segments": [{"text": " Taking some paracetamol, two tablets up to four times a day.", "start": 0.0, "end": 4.0},
                                 {"text": " Stop the ibuprofen.", "start": 4.0, "end": 6.0}, {"text": "  ", "start": 6.0, "end": 7.0}]}
    whisper.load_audio = load_audio
    whisper.load_model = lambda name, device=None: calls.append(("load_model", name, device)) or Model()
    torch = types.ModuleType("torch")
    torch.__version__ = "stand-in"
    torch.cuda = types.SimpleNamespace(is_available=lambda: False)
    torch.version = types.SimpleNamespace(hip=None)
    return {"whisper": whisper, "torch": torch}


class TestAsrLocal(unittest.TestCase):
    def setUp(self):
        self.calls, self.saved = [], {k: sys.modules.get(k) for k in ("whisper", "torch")}
        sys.modules.update(stand_ins(self.calls))
        import asr_local
        self.asr = asr_local
        asr_local._models.clear()

    def tearDown(self):
        for k, v in self.saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v
        self.asr._models.clear()

    def test_a_recording_is_written_out_line_by_line(self):
        t = self.asr.transcriber("base.en")
        out = t(SAMPLE.read_bytes(), ".wav")
        self.assertEqual(out["text"], "Taking some paracetamol, two tablets up to four times a day.\nStop the ibuprofen.")
        self.assertEqual(out["model"], "Whisper base.en")
        self.assertIn("numbers", out["needs_check"])
        self.assertIn("negations", out["needs_check"])
        self.assertEqual(self.calls[0], ("load_model", "base.en", "cpu"))
        self.assertEqual(self.calls[1], ("load_audio", ".wav", b"RIFF"))   # the bytes went to a file with their suffix
        self.assertEqual(self.calls[2], ("transcribe", 16000 * 9, "en", False))

    def test_the_model_loads_once_and_the_environment_picks_it(self):
        import os
        os.environ["CARERELAY_ASR_MODEL"] = "small.en"
        try:
            t = self.asr.transcriber()
        finally:
            os.environ.pop("CARERELAY_ASR_MODEL")
        self.assertEqual(t.model_name, "small.en")
        t(b"RIFF....", ".webm")
        t(b"RIFF....", ".webm")
        self.assertEqual([c for c in self.calls if c[0] == "load_model"], [("load_model", "small.en", "cpu")])
        self.assertEqual([c[1] for c in self.calls if c[0] == "load_audio"], [".webm", ".webm"])

    def test_missing_says_what_to_install(self):
        self.assertEqual([m for m in self.asr.missing() if m != "ffmpeg"], [])   # the stand-ins count as installed
        saved = sys.modules.pop("whisper"), sys.modules.pop("torch")
        try:
            import importlib.util
            if importlib.util.find_spec("whisper") is None:
                self.assertIn("openai-whisper", self.asr.missing())
        finally:
            sys.modules["whisper"], sys.modules["torch"] = saved


if __name__ == "__main__":
    unittest.main(verbosity=1)
