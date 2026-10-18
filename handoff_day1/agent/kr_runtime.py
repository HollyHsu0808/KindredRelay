"""Offline CPU inference; identical input formatting to training. No network calls."""
from __future__ import annotations
import hashlib, json, math, os, threading, time
from pathlib import Path

def source_input(source, question=""):
    return (f"Question: {question.strip()}\n" if question.strip() else "") + "Evidence:\n" + source.strip()

class EvidenceVerifier:
    def __init__(self, bundle, device="cpu", threads=2):
        os.environ.setdefault("USE_TF", "0"); os.environ.setdefault("USE_FLAX", "0")
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer
        self.root = Path(bundle).resolve()
        self.card = validate_bundle(self.root)
        for name, expected in self.card["artifact_sha256"].items():
            actual = hashlib.sha256((self.root / name).read_bytes()).hexdigest()
            if actual != expected: raise ValueError("Model artifact checksum mismatch: " + name)
        self.tokenizer = AutoTokenizer.from_pretrained(self.root, local_files_only=True, use_fast=False, trust_remote_code=False)
        self.model = AutoModelForSequenceClassification.from_pretrained(self.root, local_files_only=True, trust_remote_code=False)
        if self.model.config.id2label != {0: "supported", 1: "unsupported"}:
            raise ValueError("Unexpected label mapping")
        if device == "cpu": torch.set_num_threads(threads)
        self.model.to(device).eval(); self.device = device; self.lock = threading.RLock()
        self.threshold = float(self.card["support_threshold"])
        self.max_length = int(self.card["max_length"])

    def check(self, source, claim, question=""):
        import torch
        started = time.perf_counter()
        result = {"status": "unverified", "model_id": self.card["run_id"],
            "model_stage": self.card["stage"], "threshold": self.threshold,
            "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
            "claim_sha256": hashlib.sha256(claim.encode()).hexdigest(),
            "question_sha256": hashlib.sha256(question.encode()).hexdigest()}
        if not source.strip() or not claim.strip(): return {**result, "reason": "empty_input"}
        enc = self.tokenizer(source_input(source, question), claim.strip(), truncation=False, return_tensors="pt")
        n = int(enc["input_ids"].shape[-1]); result["tokens"] = n
        if n > self.max_length: return {**result, "reason": "context_too_long", "latency_ms": (time.perf_counter()-started)*1000}
        with self.lock, torch.inference_mode():
            logits = self.model(**{k:v.to(self.device) for k,v in enc.items()}).logits
            if not torch.isfinite(logits).all():
                return {**result, "reason": "nonfinite_model_output",
                    "latency_ms": (time.perf_counter()-started)*1000}
            probabilities = logits.float().softmax(-1)
            if not torch.isfinite(probabilities).all():
                return {**result, "reason": "nonfinite_model_output",
                    "latency_ms": (time.perf_counter()-started)*1000}
            p = float(probabilities[0,0].cpu())
        return {**result, "status": "supported_by_model" if p >= self.threshold else "needs_review",
            "support_score": p, "latency_ms": (time.perf_counter()-started)*1000,
            "reason": "model_score_threshold"}

    def benchmark(self, pairs, repeats=3):
        import numpy as np
        self.check(**pairs[0])  # warm-up excluded
        times = []; results = []; by_input=[[] for _ in pairs]
        for _ in range(repeats):
            for i,pair in enumerate(pairs):
                start = time.perf_counter(); result = self.check(**pair)
                elapsed=(time.perf_counter()-start)*1000
                times.append(elapsed);by_input[i].append(elapsed); results.append(result)
        return {"device": self.device, "requests": len(times), "batch_size": 1,
            "latency_ms_p50": float(np.percentile(times,50)), "latency_ms_p95": float(np.percentile(times,95)),
            "max_tokens": max(r.get("tokens",0) for r in results), "results": results,
            "per_input":[{"input_index":i,"tokens":results[i].get("tokens"),"p50_ms":float(np.percentile(t,50)),
                "p95_ms":float(np.percentile(t,95))} for i,t in enumerate(by_input)]}

def validate_bundle(bundle):
    """Validate the portable notebook's flat manifest before loading any model.

    Hashes detect corruption, not who produced a bundle. Bundle origin is still
    an operator responsibility. No pickle or remote Python code is loaded.
    """
    root = Path(bundle).resolve()
    card = json.loads((root / "verifier.json").read_text(encoding="utf-8"))
    manifest = card.get("artifact_sha256")
    if not isinstance(manifest, dict) or not manifest:
        raise ValueError("Model artifact manifest is missing")
    for name, expected in manifest.items():
        target = (root / name).resolve()
        if not isinstance(name, str) or Path(name).name != name or target.parent != root:
            raise ValueError("Model artifact path must stay inside the bundle")
        if not isinstance(expected, str) or len(expected) != 64 or any(c not in "0123456789abcdef" for c in expected):
            raise ValueError("Invalid model artifact checksum")
        if hashlib.sha256(target.read_bytes()).hexdigest() != expected:
            raise ValueError("Model artifact checksum mismatch: " + name)
    files = {p.name for p in root.iterdir() if p.is_file() and p.name != "verifier.json"}
    if files != set(manifest) or not {"config.json", "model.safetensors", "tokenizer_config.json"} <= files:
        raise ValueError("Model manifest must cover every file, including safe weights and tokenizer config")
    if any(name.endswith((".bin", ".pt", ".pkl", ".py")) for name in files):
        raise ValueError("Only safe model artifacts are supported")
    threshold = card.get("support_threshold")
    # Notebook v1.2 uses 1.000001 as the explicit reject-all operating point.
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or not math.isfinite(threshold) or not (0 <= threshold <= 1 or threshold == 1.000001):
        raise ValueError("Invalid support threshold")
    if type(card.get("max_length")) is not int or card["max_length"] <= 0:
        raise ValueError("Invalid maximum input length")
    if card.get("stage") not in ("smoke", "full") or not isinstance(card.get("run_id"), str) or not card["run_id"]:
        raise ValueError("Invalid model identity")
    return card


if __name__ == "__main__":
    import argparse
    p=argparse.ArgumentParser();p.add_argument("bundle");p.add_argument("--source",required=True);p.add_argument("--claim",required=True)
    a=p.parse_args(); print(json.dumps(EvidenceVerifier(a.bundle).check(a.source,a.claim),indent=2))
