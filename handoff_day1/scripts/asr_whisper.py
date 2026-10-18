#!/usr/bin/env python3
"""Whisper ASR -> carerelay.transcript_result/0.1.0, plus WER / real-time factor against the PriMock57 human transcript.

Runs unchanged on Kaggle (NVIDIA CUDA), a laptop (CPU, slow) and the AMD MI300X (ROCm PyTorch reports itself as
"cuda"). Backend: openai-whisper (MIT licence, code and weights). Whole-file transcription with segment timestamps;
each segment is flagged for human checking when it contains numbers, times, negations or conditions (the product
plan: those are always checked against the audio by a person).

Usage:
  # one audio file -> one transcript_result JSON
  python scripts/asr_whisper.py --audio rec.wav --input-id case-demo-001:src-B-001 --speaker clinician --out rec.json
  # evaluate on PriMock57 consultations (downloaded by scripts/download_primock57.py), both speaker channels
  python scripts/asr_whisper.py --primock day1_consultation01 --out-dir runs/asr_whisper
  # same, with the medicine / care vocabulary as a prompt
  python scripts/asr_whisper.py --primock day1_consultation01 --model large-v3 \
      --vocab-file handoff_day1/model/asr_vocabulary_en.txt --out-dir runs/asr_large_v3_vocab
Options: --model turbo (default; large-v3-turbo) | large-v3 | medium.en | small.en | base.en ; --device auto|cuda|cpu
Prompt: --vocab-file <one term per line, '#' comments> and/or --initial-prompt "<text>" (with both, the text replaces
  the lead sentence "Medical consultation."). The prompt is trimmed to Whisper's prompt window (223 tokens, counted
  with the model's own tokenizer; whole terms are dropped from the end of the list, never part of a word) and passed
  with carry_initial_prompt=True, so it conditions every 30 s window while condition_on_previous_text stays False
  (no repetition loops). --no-carry-prompt: first window only (Whisper's plain initial_prompt behaviour).
  --prompt-max-tokens N: a smaller budget. The summary JSON records the prompt text, sha256, token count and carry flag.
Evaluation (--primock) also reports WER on instruction-bearing reference segments (a number, a time word or a term of
  --eval-vocab-file, default handoff_day1/model/asr_vocabulary_en.txt) and how many vocabulary terms were recognised.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import inspect
import json
import platform
import re
import sys
import time
import uuid
import wave
from pathlib import Path

SCHEMA = "carerelay.transcript_result/0.1.0"
CHECKS = {  # categories a person must verify against the audio (product plan: numbers, negations, conditions)
    # any digit at all (500mg, 5ml, 2nd, 4h, 1.5) plus spelled-out amounts
    "numbers": r"\d|\b(zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|"
               r"sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|"
               r"thousand|million|half|quarter|once|twice|dozen|couple|few|several|single|double|first|second|third)\b",
    "times": r"\b\d{1,2}([:.]\d{2})?\s*(a\.?\s?m\.?|p\.?\s?m\.?)|\bo'?clock\b|\b(noon|midnight|morning|afternoon|evening|"
             r"night|nights|tonight|bedtime|tomorrow|yesterday|today|monday|tuesday|wednesday|thursday|friday|saturday|"
             r"sunday|daily|weekly|hourly|hours?|minutes?|days?|weeks?|months?|breakfast|lunch|dinner|meals?|"
             r"weekend|fortnight)\b",
    "negations": r"n'?t\b|\b(no|not|never|none|nothing|nobody|nowhere|neither|nor|without|cannot|avoid|stop|skip|hold|"
                 r"discontinue|no longer)\b",
    "conditions": r"\b(if|unless|before|after|until|only|when|whenever|while|as long as|in case|in the event|otherwise|"
                  r"except|provided|providing|depending|should (she|he|they|you|it))\b",
}


PROMPT_LEAD = "Medical consultation."
DEFAULT_VOCAB = Path("handoff_day1/model/asr_vocabulary_en.txt")  # relative to the project root


def project_root() -> Path:
    here = Path(__file__).resolve().parent.parent
    return here.parent if here.name == "handoff_day1" else here


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with Path(p).open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def wav_info(p: Path) -> tuple[int | None, float | None]:
    try:
        with wave.open(str(p), "rb") as w:
            return w.getframerate(), w.getnframes() / float(w.getframerate())
    except (wave.Error, EOFError, OSError):
        return None, None


def clean_msg(e, *paths) -> str:
    """An error message without machine paths or ffmpeg's build banner: last non-empty line, paths -> file names."""
    lines = [ln for ln in str(e).splitlines() if ln.strip()]
    m = lines[-1] if lines else type(e).__name__
    for p in paths:
        if p:
            m = m.replace(str(p), Path(p).name).replace(str(Path(p).resolve()), Path(p).name)
    return f"{type(e).__name__}: {m}"[:300]


def check_reasons(text: str) -> list[str]:
    t = text.lower().replace("’", "'")
    return [k for k, rx in CHECKS.items() if re.search(rx, t)]


def plain_words(text: str) -> list[str]:
    """Lowercase words without punctuation or PriMock markup (the same rule as run_asr_sample.norm_words)."""
    text = re.sub(r"</?[A-Z]+/?>", " ", text).lower()
    return re.sub(r"[^a-z0-9' ]+", " ", text).split()


def load_vocab(path: Path) -> list[str]:
    """Terms of a vocabulary file: one per line; '#' starts a comment; blank lines and repeats are ignored."""
    terms, seen = [], set()
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        term = " ".join(line.split("#", 1)[0].split())
        if term and term.lower() not in seen:
            seen.add(term.lower())
            terms.append(term)
    return terms


def build_prompt(count_tokens, limit: int, lead: str | None = None, terms=()) -> dict:
    """Prompt text that fits `limit` tokens, plus what had to go. count_tokens(text) must count the way Whisper encodes
    a prompt (transcribe.py: tokenizer.encode(" " + initial_prompt.strip())). Whole terms are dropped from the end of
    the list; only when the lead sentence alone is still too long does it lose whole words from its end."""
    terms = list(terms)
    lead_words = (lead if lead is not None else (PROMPT_LEAD if terms else "")).split()

    def compose(n_lead: int, n_terms: int) -> str:
        parts = [" ".join(lead_words[:n_lead])] if n_lead else []
        if n_terms:
            parts.append("Terms: " + ", ".join(terms[:n_terms]) + ".")
        return " ".join(parts)

    n_lead, n_terms = len(lead_words), len(terms)
    while n_terms and count_tokens(compose(n_lead, n_terms)) > limit:
        n_terms -= 1
    while n_lead and count_tokens(compose(n_lead, n_terms)) > limit:
        n_lead -= 1
    text = compose(n_lead, n_terms)
    return {"text": text, "tokens": count_tokens(text) if text else 0, "token_limit": limit,
            "lead": " ".join(lead_words[:n_lead]), "lead_words_dropped": len(lead_words) - n_lead,
            "terms_total": len(terms), "terms_used": n_terms, "terms_dropped": terms[n_terms:]}


def prompt_echo(text: str, echo_terms: list[str], echo_lead: str) -> bool:
    """Heuristic for a segment that repeats the prompt instead of the audio: the prompt's 'Terms:' label, three prompt
    terms in a row, the lead sentence as the whole segment, or six words of a longer lead in a row."""
    if "terms:" in text.lower():
        return True
    words = " " + " ".join(plain_words(text)) + " "
    if echo_lead and words.strip() == echo_lead:
        return True
    if any(f" {' '.join(echo_terms[i:i + 3])} " in words for i in range(len(echo_terms) - 2)):
        return True
    lw = echo_lead.split()
    return any(f" {' '.join(lw[i:i + 6])} " in words for i in range(len(lw) - 5))


def align(ref: list[str], hyp: list[str]) -> list[tuple]:
    """Word alignment with the minimum number of edits (the same count as run_asr_sample.wer), as a list of
    (op, ref_index, hyp_index); op is 'eq', 'sub', 'del' (reference word missed) or 'ins' (extra hypothesis word)."""
    n, m = len(ref), len(hyp)
    back = [bytearray(m + 1) for _ in range(n + 1)]  # 0 diagonal, 1 deletion, 2 insertion
    back[0][1:] = b"\x02" * m
    prev = list(range(m + 1))
    for i in range(1, n + 1):
        r, row, cur = ref[i - 1], back[i], [i] + [0] * m
        row[0] = 1
        for j in range(1, m + 1):
            d, u, left = prev[j - 1] + (r != hyp[j - 1]), prev[j] + 1, cur[j - 1] + 1
            if d <= u and d <= left:
                cur[j] = d
            elif u <= left:
                cur[j], row[j] = u, 1
            else:
                cur[j], row[j] = left, 2
        prev = cur
    ops, i, j = [], n, m
    while i or j:
        b = back[i][j]
        if b == 0:
            ops.append(("eq" if ref[i - 1] == hyp[j - 1] else "sub", i - 1, j - 1))
            i, j = i - 1, j - 1
        elif b == 1:
            ops.append(("del", i - 1, None))
            i -= 1
        else:
            ops.append(("ins", None, j - 1))
            j -= 1
    ops.reverse()
    return ops


def subset_wer(ref_segs: list[list[str]], hyp: list[str], keep: list[bool]) -> dict:
    """WER on the reference segments with keep[k] True, from one whole-channel alignment: errors on their words plus
    inserted words that follow one of their words (an insertion before the first reference word goes with the first
    segment). Also returns the flat reference, the alignment and the total edits for reuse."""
    ref = [w for ws in ref_segs for w in ws]
    owner = [k for k, ws in enumerate(ref_segs) for _ in ws]
    ops = align(ref, hyp)
    edits, last = 0, (owner[0] if owner else None)
    for op, i, _ in ops:
        if op == "ins":
            edits += last is not None and keep[last]
        else:
            last = owner[i]
            edits += op != "eq" and keep[last]
    ref_words = sum(len(ws) for ws, k in zip(ref_segs, keep) if k)
    return {"edits": int(edits), "ref_words": ref_words, "wer": round(edits / ref_words, 4) if ref_words else None,
            "edits_total": sum(op != "eq" for op, _, _ in ops), "ref": ref, "ops": ops}


def term_counts(ref: list[str], hyp: list[str], ops: list[tuple], terms: dict[str, list[str]]) -> dict[str, dict]:
    """Per vocabulary term (given as its word list): occurrences in the reference, how many of them were recognised
    word for word (every word aligned as equal), occurrences in the hypothesis, and how many of those are not aligned
    to the same reference words (the ASR wrote the term where it was not said)."""
    ok_ref, ok_hyp = [False] * len(ref), [False] * len(hyp)
    for op, i, j in ops:
        if op == "eq":
            ok_ref[i] = ok_hyp[j] = True

    def starts(words: list[str], tw: list[str]) -> list[int]:
        n = len(tw)
        return [s for s in range(len(words) - n + 1) if words[s] == tw[0] and words[s:s + n] == tw]
    out = {}
    for term, tw in terms.items():
        r, h = starts(ref, tw), starts(hyp, tw)
        if r or h:
            out[term] = {"ref": len(r), "hit": sum(all(ok_ref[s:s + len(tw)]) for s in r), "hyp": len(h),
                         "hyp_unmatched": sum(not all(ok_hyp[s:s + len(tw)]) for s in h)}
    return out


def instruction_bearing(text: str, term_phrases: list[str]) -> bool:
    """A reference segment with instruction content: a number or a time word (the needs-check patterns) or a term of
    the evaluation vocabulary (term_phrases: each term as space-joined plain_words)."""
    t = text.lower().replace("’", "'")
    if re.search(CHECKS["numbers"], t) or re.search(CHECKS["times"], t):
        return True
    words = " " + " ".join(plain_words(text)) + " "
    return any(f" {p} " in words for p in term_phrases)


def failed(input_id: str, code: str, message: str, retryable: bool = False, **extra) -> dict:
    return {"schema_version": SCHEMA, "input_id": input_id, "source_revision": extra.get("source_revision", "unknown"),
            "run_id": f"run-{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}",
            "result_kind": "inference", "transcript_source": "asr", "processing_status": "failed", "asr": None,
            "segments": [], "quality": {"audio_available": extra.get("audio_available", False), "reason": message},
            "runtime": None, "error": {"code": code, "message": message, "retryable": retryable}}


class AudioDecodeError(Exception):
    pass


class WhisperASR:
    def __init__(self, model_name: str, device: str = "auto"):
        import torch
        import whisper
        self.torch = torch
        self.whisper = whisper
        self.device = ("cuda" if torch.cuda.is_available() else "cpu") if device == "auto" else device
        t0 = time.perf_counter()
        self.model = whisper.load_model(model_name, device=self.device)
        self.load_s = time.perf_counter() - t0
        # a local checkpoint (e.g. weights copied to the droplet) is recorded by file name only, never by machine path
        self.model_name = Path(model_name).name if Path(model_name).is_file() else model_name
        self.version = getattr(whisper, "__version__", "unknown")
        self.prompt = None  # set_prompt(): what is passed as initial_prompt, recorded in every result
        self._echo_terms, self._echo_lead = [], ""

    def set_prompt(self, lead: str | None, terms: list[str], language: str = "en", max_tokens: int | None = None,
                   carry: bool = True, vocab_file: Path | None = None) -> dict:
        """Builds the prompt with the model's own tokenizer and Whisper's real prompt window. decoding.py keeps
        prompt_tokens[-(n_text_ctx // 2 - 1):] after <|startofprev|>, i.e. 223 tokens: anything longer loses its
        START, which is where the lead sentence and the most important terms are, so it is trimmed here instead."""
        tok = self.whisper.tokenizer.get_tokenizer(self.model.is_multilingual, num_languages=self.model.num_languages,
                                                   language=language, task="transcribe")
        window = self.model.dims.n_text_ctx // 2 - 1
        limit = min(window, max_tokens) if max_tokens else window
        p = build_prompt(lambda text: len(tok.encode(" " + text.strip())), limit, lead, terms)
        if not p["text"]:
            raise ValueError(f"the prompt does not fit in {limit} tokens")
        # carry_initial_prompt exists from openai-whisper 20250625: the prompt is put in front of every 30 s window.
        # Without it, initial_prompt conditions the first window only when condition_on_previous_text=False.
        supported = "carry_initial_prompt" in inspect.signature(self.model.transcribe).parameters
        if carry and not supported:
            print(f"warning: openai-whisper {self.version} has no carry_initial_prompt, so the prompt conditions the "
                  "first 30 s window only (condition_on_previous_text stays False to avoid repetition loops); "
                  "install the pinned version from handoff_day1/model/requirements-asr.txt", flush=True)
        carried = bool(carry and supported)
        self.prompt = {
            "text": p["text"], "sha256": hashlib.sha256(p["text"].encode("utf-8")).hexdigest(), "tokens": p["tokens"],
            "token_limit": limit, "prompt_window_tokens": window,
            "tokenizer": f"{tok.encoding.name.removesuffix('.tiktoken')} (whisper {self.version})",
            "carry_initial_prompt": carried,
            "applies_to": "every 30 s window (carry_initial_prompt=True)" if carried else "first 30 s window only",
            "lead": p["lead"], "lead_words_dropped": p["lead_words_dropped"],
            "vocab_file": Path(vocab_file).name if vocab_file else None,
            "vocab_sha256": sha256_file(vocab_file) if vocab_file else None,
            "terms_total": p["terms_total"], "terms_used": p["terms_used"], "terms_dropped": p["terms_dropped"],
            "echo_check": "segments that look like a repeat of the prompt get check_reasons 'prompt_echo'"}
        self._echo_terms = [" ".join(plain_words(t)) for t in terms[:p["terms_used"]]]
        self._echo_lead = " ".join(plain_words(p["lead"]))
        return self.prompt

    def transcribe(self, path: Path, input_id: str, speaker: str, language: str = "en", word_timestamps: bool = False,
                   source: dict | None = None) -> dict:
        """Raises AudioDecodeError for input that cannot be decoded or holds no audio."""
        torch = self.torch
        sr, _ = wav_info(path)  # original sample rate if it is a WAV (None otherwise)
        try:
            audio = self.whisper.load_audio(str(path))  # ffmpeg decode to 16 kHz mono, any format
        except Exception as e:  # noqa: BLE001
            raise AudioDecodeError(clean_msg(e, path)) from e
        if len(audio) == 0:
            raise AudioDecodeError("the file holds no audio samples")
        dur = len(audio) / float(self.whisper.audio.SAMPLE_RATE)  # duration from the decoded audio, for any format
        if self.device == "cuda":
            torch.cuda.reset_peak_memory_stats()
        started = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
        t0 = time.perf_counter()
        prompt_kw = {}
        if self.prompt:
            prompt_kw["initial_prompt"] = self.prompt["text"]
            if self.prompt["carry_initial_prompt"]:
                prompt_kw["carry_initial_prompt"] = True
        out = self.model.transcribe(audio, language=language, task="transcribe", fp16=(self.device == "cuda"),
                                    condition_on_previous_text=False,  # avoids repetition loops on long audio
                                    word_timestamps=word_timestamps, verbose=None, **prompt_kw)
        wall = time.perf_counter() - t0
        slug = re.sub(r"[^A-Za-z0-9]+", "-", input_id).strip("-")
        segs, reasons_all = [], set()
        for i, s in enumerate(out.get("segments", [])):
            text = s["text"].strip()
            if not text:
                continue
            reasons = check_reasons(text)
            if self.prompt and prompt_echo(text, self._echo_terms, self._echo_lead):
                reasons.append("prompt_echo")
            reasons_all.update(reasons)
            seg = {"segment_id": f"{slug}-asr-{i:04d}", "speaker": speaker, "start_s": round(float(s["start"]), 3),
                   "end_s": round(float(s["end"]), 3), "text": text, "text_plain": text, "confidence": None,
                   "check_reasons": reasons, "avg_logprob": round(float(s.get("avg_logprob", 0.0)), 4),
                   "no_speech_prob": round(float(s.get("no_speech_prob", 0.0)), 4),
                   "compression_ratio": round(float(s.get("compression_ratio", 0.0)), 3)}
            if word_timestamps and s.get("words"):
                seg["words"] = [{"word": w["word"], "start_s": round(float(w["start"]), 3), "end_s": round(float(w["end"]), 3),
                                 "probability": round(float(w.get("probability", 0.0)), 4)} for w in s["words"]]
            segs.append(seg)
        gpu = torch.cuda.get_device_name(0) if self.device == "cuda" else None
        return {"schema_version": SCHEMA, "input_id": input_id, "source": source or {"relative_path": path.name, "speaker": speaker},
                "source_revision": f"sha256:{sha256_file(path)}",
                "run_id": f"run-{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}",
                "result_kind": "inference", "transcript_source": "asr", "processing_status": "completed",
                "asr": {"backend": "openai-whisper", "version": self.version, "model": self.model_name, "language": language,
                        "segmentation": "whisper segments (whole-file transcription)", "condition_on_previous_text": False,
                        "temperature": "openai-whisper default fallback schedule", "word_timestamps": word_timestamps,
                        "initial_prompt": self.prompt},
                "timeline": "seconds on the audio file",
                "segments": segs,
                "quality": {"audio_available": True, "reason": None, "sample_rate": sr, "duration_s": round(dur, 3) if dur else None,
                            "needs_human_check": sorted(reasons_all),
                            "needs_human_check_note": "segments with numbers, times, negations or conditions are listed in "
                                                      "segments[].check_reasons and must be checked against the audio"},
                "runtime": {"device": self.device, "gpu": gpu, "torch": torch.__version__,
                            "torch_hip_version": getattr(torch.version, "hip", None), "python": platform.python_version(),
                            "model_load_s": round(self.load_s, 2), "transcribe_wall_s": round(wall, 2),
                            "real_time_factor": round(wall / dur, 4) if dur else None,
                            "peak_gpu_mem_gb": round(torch.cuda.max_memory_allocated() / 1e9, 2) if self.device == "cuda" else None,
                            "started_utc": started, "finished_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")},
                "error": None}


def main() -> int:
    root = project_root()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--audio", type=Path, help="one audio file (WAV preferred; anything ffmpeg reads works)")
    ap.add_argument("--input-id", default=None)
    ap.add_argument("--speaker", default="unknown")
    ap.add_argument("--out", type=Path, help="output JSON for --audio")
    ap.add_argument("--primock", nargs="*", default=None, help="PriMock57 consultation ids to evaluate (both channels)")
    ap.add_argument("--raw", type=Path, default=root / "data/raw/primock57")
    ap.add_argument("--out-dir", type=Path, default=root / "runs/asr_whisper")
    ap.add_argument("--model", default="turbo")
    ap.add_argument("--device", default="auto")
    ap.add_argument("--language", default="en")
    ap.add_argument("--word-timestamps", action="store_true")
    ap.add_argument("--vocab-file", type=Path, default=None,
                    help="terms for the Whisper prompt, one per line ('#' comments), e.g. " + str(DEFAULT_VOCAB))
    ap.add_argument("--initial-prompt", default=None,
                    help="prompt text; with --vocab-file it replaces the lead sentence 'Medical consultation.'")
    ap.add_argument("--prompt-max-tokens", type=int, default=None,
                    help="token budget below Whisper's prompt window (223 tokens)")
    ap.add_argument("--no-carry-prompt", action="store_true",
                    help="prompt the first 30 s window only (default: every window, carry_initial_prompt=True)")
    ap.add_argument("--eval-vocab-file", type=Path, default=None,
                    help="term list for the evaluation's instruction-bearing WER and term recall (keep it the same "
                         "across runs that are compared); default " + str(DEFAULT_VOCAB))
    args = ap.parse_args()
    if args.eval_vocab_file is not None and not args.eval_vocab_file.is_file():
        ap.error(f"--eval-vocab-file not found: {args.eval_vocab_file}")
    if args.eval_vocab_file is None:
        args.eval_vocab_file = root / DEFAULT_VOCAB
        if args.primock is not None and not args.eval_vocab_file.is_file():
            print(f"WARNING: the default evaluation term list {args.eval_vocab_file} is missing: the instruction-bearing "
                  "WER counts numbers and time words only, and term recall is null", file=sys.stderr)
    if not args.audio and args.primock is None:
        ap.error("give --audio (+ --out) or --primock <consultation ids>")
    vocab_terms = None
    if args.vocab_file is not None:
        if not args.vocab_file.is_file():
            ap.error(f"--vocab-file {args.vocab_file.name} not found")
        vocab_terms = load_vocab(args.vocab_file)
        if not vocab_terms:
            ap.error(f"--vocab-file {args.vocab_file.name} holds no terms")
    if args.initial_prompt is not None and not args.initial_prompt.strip():
        ap.error("--initial-prompt is empty")
    use_prompt = vocab_terms is not None or args.initial_prompt is not None
    if args.prompt_max_tokens is not None and (args.prompt_max_tokens < 1 or not use_prompt):
        ap.error("--prompt-max-tokens needs a positive number and --vocab-file or --initial-prompt")

    def write_failure(res: dict) -> int:  # --audio mode always writes a result JSON, as the other runners do
        if args.audio:
            out = args.out or args.audio.with_suffix(".transcript_result.json")
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(res, indent=2, ensure_ascii=False), encoding="utf-8")
        print(json.dumps(res["error"]))
        return 1

    input_id = args.input_id or (f"file:{args.audio.name}" if args.audio else "unknown")
    local_ckpt = args.model.endswith(".pt") or "/" in args.model or "\\" in args.model
    if local_ckpt and not Path(args.model).is_file():
        return write_failure(failed(input_id, "model_unavailable", f"local checkpoint {Path(args.model).name} not found"))
    try:
        asr = WhisperASR(args.model, args.device)
    except ImportError as e:
        return write_failure(failed(input_id, "dependency_missing", f"{e}; pip install -r handoff_day1/model/requirements-asr.txt"))
    except Exception as e:  # noqa: BLE001  (model download blocked, CUDA problems)
        return write_failure(failed(input_id, "model_unavailable", clean_msg(e, args.model), retryable=not local_ckpt))
    print(f"whisper {asr.version} model {asr.model_name} on {asr.device} (load {asr.load_s:.1f}s)", flush=True)
    if use_prompt:
        try:
            pr = asr.set_prompt(args.initial_prompt, vocab_terms or [], args.language, args.prompt_max_tokens,
                                carry=not args.no_carry_prompt, vocab_file=args.vocab_file)
        except ValueError as e:
            ap.error(str(e))
        print(f"prompt: {pr['tokens']}/{pr['token_limit']} tokens ({pr['tokenizer']}), terms {pr['terms_used']}/"
              f"{pr['terms_total']}, {pr['applies_to']}, sha256 {pr['sha256'][:12]}", flush=True)

    if args.audio:
        if args.audio.is_dir():
            res = failed(input_id, "input_unreadable", f"{args.audio.name} is a directory, not an audio file")
        elif not args.audio.is_file():
            res = failed(input_id, "input_not_found", f"{args.audio.name} not found")
        else:
            try:
                res = asr.transcribe(args.audio, input_id, args.speaker, args.language, args.word_timestamps)
            except AudioDecodeError as e:
                res = failed(input_id, "input_unreadable", str(e), audio_available=False)
            except Exception as e:  # noqa: BLE001  (e.g. GPU out of memory): not the input's fault
                res = failed(input_id, "internal_error", clean_msg(e, args.audio, args.model), retryable=True)
        out = args.out or args.audio.with_suffix(".transcript_result.json")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(res, indent=2, ensure_ascii=False), encoding="utf-8")
        print(json.dumps({"out": str(out), "status": res["processing_status"], "segments": len(res["segments"]),
                          "rtf": (res.get("runtime") or {}).get("real_time_factor"), "error": res["error"]}))
        return 0 if res["processing_status"] == "completed" else 1

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from primock_transcript_segments import parse_textgrid  # noqa: E402
    from run_asr_sample import norm_words, wer  # noqa: E402
    from whisper.normalizers import EnglishTextNormalizer  # noqa: E402
    _en = EnglishTextNormalizer()

    def english_norm(text: str) -> str:
        return _en(re.sub(r"</?[A-Za-z]+/?>", " ", text))  # PriMock markup tags out first
    # fixed term list for the instruction-bearing view and term recall, the same whether or not a prompt is used
    ev = args.eval_vocab_file
    eval_terms = load_vocab(ev) if ev and ev.is_file() else []
    term_words = {t: w for t in eval_terms if (w := norm_words(t))}
    term_phrases = [" ".join(w) for w in term_words.values()]
    term_totals: dict[str, dict] = {}
    args.out_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for c in args.primock or ["day1_consultation01"]:
        for role in ("doctor", "patient"):
            wav = args.raw / f"audio/{c}_{role}.wav"
            tg = args.raw / f"transcripts/{c}_{role}.TextGrid"
            if not wav.is_file() or not tg.is_file():
                print(f"skip {c} {role}: missing {wav if not wav.is_file() else tg} (run scripts/download_primock57.py --consultation {c})")
                continue
            res = asr.transcribe(wav, f"primock57:{c}:{role}", role, args.language, args.word_timestamps,
                                 source={"dataset": "PriMock57", "relative_path": f"audio/{c}_{role}.wav", "speaker": role,
                                         "licence": "CC BY 4.0"})
            (args.out_dir / f"{c}_{role}.transcript_result.json").write_text(json.dumps(res, indent=2, ensure_ascii=False), encoding="utf-8")
            _, ref_segs = parse_textgrid(tg)
            ref_text = " ".join(s["text"] for s in ref_segs)
            hyp_text = " ".join(s["text"] for s in res["segments"])
            w = wer(norm_words(ref_text), norm_words(hyp_text))
            # Whisper's English normaliser: drops fillers (um, uh), writes numbers as digits, unifies spellings, so
            # "two tablets" vs "2 tablets" and a dropped "uh" are not counted as recognition errors
            wn = wer(english_norm(ref_text).split(), english_norm(hyp_text).split())
            # instruction-bearing view: the same whole-channel alignments, counted on the reference segments with a
            # number, a time word or a vocabulary term (what a care instruction is made of)
            keep = [instruction_bearing(s["text_plain"], term_phrases) for s in ref_segs]
            hyp_words = norm_words(hyp_text)
            wi = subset_wer([norm_words(s["text"]) for s in ref_segs], hyp_words, keep)
            win = subset_wer([english_norm(s["text"]).split() for s in ref_segs], english_norm(hyp_text).split(), keep)
            tc = term_counts(wi["ref"], hyp_words, wi["ops"], term_words)
            for t, cnt in tc.items():
                tot = term_totals.setdefault(t, {"ref": 0, "hit": 0, "hyp": 0, "hyp_unmatched": 0})
                for k2, v2 in cnt.items():
                    tot[k2] += v2
            row = {"consultation": c, "speaker": role, "duration_s": res["quality"]["duration_s"], **w,
                   "wer_normalized": wn["wer"], "edits_normalized": wn["edits"], "ref_words_normalized": wn["ref_words"],
                   "rtf": res["runtime"]["real_time_factor"], "segments": len(res["segments"]),
                   "segments_needing_check": sum(1 for s in res["segments"] if s["check_reasons"]),
                   "wer_instruction": wi["wer"], "edits_instruction": wi["edits"], "ref_words_instruction": wi["ref_words"],
                   "wer_instruction_normalized": win["wer"], "edits_instruction_normalized": win["edits"],
                   "ref_words_instruction_normalized": win["ref_words"],
                   "ref_segments": len(ref_segs), "ref_segments_instruction": sum(keep),
                   "vocab_terms_ref": sum(v["ref"] for v in tc.values()), "vocab_terms_hit": sum(v["hit"] for v in tc.values()),
                   "vocab_terms_hyp_unmatched": sum(v["hyp_unmatched"] for v in tc.values()),
                   "segments_prompt_echo": sum(1 for s in res["segments"] if "prompt_echo" in s["check_reasons"]),
                   "transcribe_wall_s": res["runtime"]["transcribe_wall_s"]}
            rows.append(row)
            print(f"{c} {role}: WER {w['wer']} ({w['edits']}/{w['ref_words']}), normalised WER {wn['wer']}, "
                  f"instruction-bearing WER {wi['wer']} / normalised {win['wer']}, RTF {row['rtf']}, "
                  f"segments {row['segments']}", flush=True)
    tot_e = sum(r["edits"] for r in rows); tot_r = sum(r["ref_words"] for r in rows)
    tot_en = sum(r["edits_normalized"] for r in rows); tot_rn = sum(r["ref_words_normalized"] for r in rows)

    def ratio(key_e: str, key_r: str):
        e, r = sum(x[key_e] for x in rows), sum(x[key_r] for x in rows)
        return round(e / r, 4) if r else None
    t_ref = sum(v["ref"] for v in term_totals.values())
    audio_s = sum(r["duration_s"] or 0 for r in rows); wall_s = sum(r["transcribe_wall_s"] or 0 for r in rows)
    summary = {"model": asr.model_name, "whisper": asr.version, "device": asr.device,
               "gpu": asr.torch.cuda.get_device_name(0) if asr.device == "cuda" else None,
               "wer_definition": "summed word edits / summed reference words after lowercasing and removing punctuation and "
                                 "PriMock markup; whole-channel alignment",
               "corpus_wer": round(tot_e / tot_r, 4) if tot_r else None,
               "corpus_wer_normalized": round(tot_en / tot_rn, 4) if tot_rn else None,
               "wer_normalized_definition": "same alignment after whisper.normalizers.EnglishTextNormalizer on both sides "
                                            "(fillers removed, numbers as digits, spellings unified): the usual Whisper WER",
               "corpus_wer_instruction": ratio("edits_instruction", "ref_words_instruction"),
               "corpus_wer_instruction_normalized": ratio("edits_instruction_normalized", "ref_words_instruction_normalized"),
               "wer_instruction_definition": "the same whole-channel alignments, counted only on reference segments that "
                                             "carry instruction content: a number or a time word (the needs-check "
                                             "patterns) or a term of the evaluation vocabulary; an inserted word counts "
                                             "with the segment of the reference word before it",
               "vocab_term_recall": round(sum(v["hit"] for v in term_totals.values()) / t_ref, 4) if t_ref else None,
               "vocab_term_false_alarms": sum(v["hyp_unmatched"] for v in term_totals.values()),
               "vocab_term_definition": "recall = reference occurrences of evaluation-vocabulary terms recognised word for "
                                        "word / all reference occurrences; false alarms = terms in the ASR text not "
                                        "aligned to the same reference words (lowercase, punctuation removed)",
               "vocab_terms": dict(sorted(term_totals.items())),
               "eval_vocabulary": ({"file": ev.name, "sha256": sha256_file(ev), "terms": len(eval_terms)}
                                   if eval_terms else None),
               "prompt": asr.prompt,
               "audio_s": round(audio_s, 2), "transcribe_wall_s": round(wall_s, 2),
               "real_time_factor": round(wall_s / audio_s, 4) if audio_s else None,
               "segments": sum(r["segments"] for r in rows),
               "segments_needing_check": sum(r["segments_needing_check"] for r in rows),
               "segments_prompt_echo": sum(r["segments_prompt_echo"] for r in rows),
               "channels": rows,
               "note": "a few consultations are a smoke test, not a benchmark; PriMock57 is role-played (CC BY 4.0)"}
    (args.out_dir / "asr_eval_summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps({k: summary[k] for k in ("model", "device", "gpu", "corpus_wer", "corpus_wer_normalized",
                                              "corpus_wer_instruction", "corpus_wer_instruction_normalized",
                                              "vocab_term_recall", "real_time_factor")}
                     | {"prompt_sha256": (asr.prompt or {}).get("sha256")}))
    return 0 if rows else 1


if __name__ == "__main__":
    sys.exit(main())
