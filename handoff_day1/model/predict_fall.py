#!/usr/bin/env python3
"""CareRelay fall model on one video -> carerelay.model_result JSON (same contract as predict.py).

Models (fall_gru.MODELS):
  carerelay (default)  CareRelay fall GRU, MediaPipe pose front end (Apache-2.0), trained on GMDCSA-24 Subjects 1-2,
                       threshold from Subject 3 (scripts/train_fall_gru.py)
  g2 / g4              A2 notebook models trained on Le2i with the YOLOv8n-pose front end (AGPL-3.0)
Pipeline (fall_gru.py): pose front end -> one sample every 0.2 s of PTS -> 12 pose features -> the model's
normaliser -> GRU over the last 10 samples -> per-sample sigmoid. Clip label: fall if max score >= threshold.
Evidence: the causal window at the peak sample plus every run of consecutive above-threshold samples (PTS seconds).
Scores are uncalibrated.

Usage:
  python predict_fall.py --video ../integration_samples/gmdcsa24/s1_fall_01.mp4 --out /tmp/s1_fall_01.json
  python predict_fall.py --video <clip.mp4> --model g4 --out <out.json>                  # legacy G4 (YOLO front end)
  python predict_fall.py --video <clip.mp4> --model g4 --pose-frontend mediapipe ...     # G4 on MediaPipe poses
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import platform
import sys
import time
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
try:
    import fall_gru as F  # noqa: E402  (imports numpy)
    _F_IMPORT_ERROR = None
except (ImportError, OSError) as _e:  # reported as dependency_missing by run(), never a bare traceback
    F, _F_IMPORT_ERROR = None, _e
from predict import WEIGHTS as V1_WEIGHTS, base_result, ffprobe_streams, manifest_row, r4, sha256_file  # noqa: E402

MAX_WINDOW_EVIDENCE = 5


def rel(p: Path, base: Path) -> str:
    """Path relative to the weights folder when inside it, else as given (no absolute machine paths when avoidable)."""
    try:
        return str(Path(p).resolve().relative_to(Path(base).resolve()))
    except ValueError:
        return str(p)


def training_data_text(s: dict) -> str:
    """Which data trained the model (v0.1: one dataset; multi-dataset runs: train_sets from train_fall_gru_multi.py)."""
    d = s.get("data")
    if not d:
        return "Le2i / IMVIA (A2 notebook); not GMDCSA-24"
    if d.get("train_sets"):
        return ("; ".join(f"{k} subjects {v}" for k, v in d["train_sets"].items())
                + f" (threshold: {', '.join(d.get('validation', {}).get('sets', []))})")
    return f"{d['dataset']} subjects {d['train']['subjects']} (threshold: subject {d['validation']['subjects']})"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--video", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--model", choices=sorted(F.MODELS) if F else ["carerelay", "g2", "g4"], default="carerelay")
    ap.add_argument("--model-dir", type=Path, default=None,
                    help="use this trained model directory instead of the --model default (e.g. a new run from train_fall_gru.py)")
    ap.add_argument("--pose-frontend", choices=["auto", "mediapipe", "yolo"], default="auto",
                    help="auto = the front end the model was trained with")
    ap.add_argument("--input-id", default=None, help="e.g. gmdcsa24:s1_fall_01")
    ap.add_argument("--manifest", type=Path, default=HERE.parent / "dataset_manifest.csv",
                    help="optional: fills input.dataset/split/... by sha256 lookup")
    ap.add_argument("--weights-dir", type=Path, default=HERE / "weights")
    ap.add_argument("--device", default="cpu", help="YOLO front end only: 'cpu' or e.g. '0' (MediaPipe runs on CPU)")
    ap.add_argument("--samples-out", type=Path, default=None, help="optional per-sample CSV (pts, features, score)")
    args = ap.parse_args()

    started = dt.datetime.now(dt.timezone.utc)
    run_id = f"run-{started.strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    res = base_result(args, args.video, None, run_id)

    def finish(code: str | None = None, message: str = "", retryable: bool = False) -> int:
        if code:
            res["processing_status"] = "failed"
            res["prediction"]["label"] = None
            res["error"] = {"code": code, "message": message, "retryable": retryable}
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(res, indent=2))
        print(json.dumps({"out": str(args.out), "status": res["processing_status"],
                          "label": res["prediction"]["label"], "score": res["prediction"]["score"],
                          "error": res["error"]}))
        return 0 if res["processing_status"] != "failed" else 1

    try:
        return run(args, res, finish, started)
    except Exception as e:  # noqa: BLE001 - last resort: never exit without a JSON
        return finish("internal_error", f"{type(e).__name__}: {e}")


def run(args, res, finish, started) -> int:
    video = args.video
    if not video.exists():
        return finish("input_not_found", f"{video} does not exist")
    if not video.is_file():
        return finish("input_unreadable", f"{video} is not a regular file")
    try:
        sha = sha256_file(video)
    except OSError as e:
        return finish("input_unreadable", f"cannot read {video}: {e}")
    res["input"]["sha256"] = sha
    res["source_revision"] = f"sha256:{sha}"
    row = manifest_row(args.manifest, sha)
    if row:
        res["input"].update(dataset="GMDCSA-24", relative_path=row["relative_path"], split=row["split"],
                            source_commit=row["source_commit"], duration_s=float(row["duration_s"]))
        if not args.input_id:
            res["input_id"] = f"gmdcsa24:{row['clip_id']}"

    try:
        probe = ffprobe_streams(video)
    except FileNotFoundError:
        return finish("dependency_missing", "ffprobe not found on PATH (install ffmpeg)")
    if not probe:
        return finish("input_unreadable", "ffprobe could not read the file")
    if not probe["video_present"]:
        res["quality"]["audio"]["stream_present"] = probe["audio_present"]
        res["quality"]["video"].update(stream_present=False, reason="no video stream in file")
        return finish("no_video_stream", "file has no video stream")
    res["quality"]["video"]["stream_present"] = True  # every later failure still says the stream exists
    res["quality"]["audio"]["stream_present"] = probe["audio_present"]
    if not (probe["video_duration_s"] or probe["duration_s"]) and probe["video_start_s"] is None:
        res["quality"]["video"]["reason"] = "no container timing (no duration, no start time)"
        return finish("input_unreadable", "no container timing (raw elementary stream?); the time axis would be invented. "
                                          "Remux with the real frame rate, e.g. ffmpeg -r <fps> -i in -c copy out.mp4")

    # ---- model + front end
    if F is None:
        return finish("dependency_missing", f"{type(_F_IMPORT_ERROR).__name__}: {_F_IMPORT_ERROR}")
    mdir = args.model_dir or F.model_dir(args.model, args.weights_dir)
    try:
        import cv2
        import numpy as np
        import torch
    except (ImportError, OSError) as e:
        return finish("dependency_missing", f"{type(e).__name__}: {e}")
    t_load = time.perf_counter()
    try:
        model = F.PoseGRUScorer(mdir)
    except FileNotFoundError as e:
        return finish("model_unavailable", f"model files missing in {mdir}: {e}")
    except Exception as e:  # noqa: BLE001
        return finish("model_unavailable", f"could not load {mdir}: {type(e).__name__}: {e}")
    front = model.front_end if args.pose_frontend == "auto" else args.pose_frontend
    pose_info = {}
    if front == "mediapipe":
        try:
            import mediapipe
            from mediapipe.tasks.python.core import mediapipe_c_bindings
            mediapipe_c_bindings.load_raw_library()  # loads libmediapipe.so -> libEGL.so.1 / libGLESv2.so.2 (lazy otherwise)
        except (ImportError, OSError, AttributeError) as e:
            return finish("dependency_missing", f"mediapipe: {type(e).__name__}: {e} "
                                                "(pip install -r requirements-mediapipe.txt; apt-get install -y libegl1 libgles2)")
        mp_path = args.weights_dir / F.MEDIAPIPE_MODEL["file"]
        if not mp_path.is_file():
            return finish("model_unavailable", f"MediaPipe model not found at {mp_path} (run fetch_weights.py)")
        try:
            pose_info = F.verify_mediapipe_model(mp_path)
        except (ValueError, OSError) as e:
            return finish("model_unavailable", f"{type(e).__name__}: {e}")
        pose_info["mediapipe"] = mediapipe.__version__
    else:
        try:
            import ultralytics
            from ultralytics import YOLO
        except (ImportError, OSError) as e:
            return finish("dependency_missing", f"ultralytics: {type(e).__name__}: {e}")
        w = V1_WEIGHTS["pose"]
        yolo_path = args.weights_dir / w["file"]
        if not yolo_path.is_file():
            return finish("model_unavailable", f"YOLO pose weights not found at {yolo_path} (run fetch_weights.py)")
        try:
            got = sha256_file(yolo_path)
        except OSError as e:
            return finish("model_unavailable", f"cannot read {yolo_path}: {e}")
        if got != w["sha256"]:
            return finish("model_unavailable", f"YOLO pose weights sha256 mismatch: {got}")
        try:
            pose_model = YOLO(str(yolo_path))
        except Exception as e:  # noqa: BLE001
            return finish("model_unavailable", f"could not load YOLO pose: {type(e).__name__}: {e}")
        pose_info = {**w, "sha256": got, "sha256_verified_against_expected": True, "ultralytics": ultralytics.__version__}
    load_s = time.perf_counter() - t_load

    # ---- features + scores
    v_start = probe["video_start_s"] or 0.0
    t0 = time.perf_counter()
    frames_total = frames_person = None
    ystats = {}
    try:
        if front == "mediapipe":
            pts, raw, arrays = F.mediapipe_features(video, mp_path, v_start)
            frames_total = int(len(arrays["pts_s"])); frames_person = int(arrays["n_persons"].sum())
        else:
            pts, raw = F.yolo_features(pose_model, video, v_start, args.device, stats=ystats)
    except F.VideoOpenError as e:
        res["quality"]["video"]["reason"] = str(e)
        return finish("input_unreadable", f"OpenCV could not open the video: {e}")
    except F.NoTimestampsError as e:
        res["quality"]["video"]["reason"] = "no advancing frame timestamps"
        return finish("input_unreadable", str(e))
    except OSError as e:  # e.g. a native library failing to load inside MediaPipe
        return finish("dependency_missing", f"{type(e).__name__}: {e}")
    pose_s = time.perf_counter() - t0
    if len(pts) == 0:  # ffprobe found a video stream (checked above) but no frame decoded
        res["quality"]["video"].update(stream_present=True, reason="video stream present but no frame could be decoded")
        res["quality"]["audio"]["stream_present"] = probe["audio_present"]
        return finish("input_unreadable", "video stream present but no frame could be decoded "
                                          "(truncated/corrupt file or a codec OpenCV cannot decode)")
    scores = model.score(raw)
    infer_s = time.perf_counter() - t0

    thr = model.threshold
    peak = int(np.argmax(scores))
    above = scores >= thr
    label = "fall" if bool(above.any()) else "no_fall"
    person = raw[:, 8] > 0
    seen = bool(person.any())
    src = {"input_id": res["input_id"], "relative_path": res["input"]["relative_path"] or video.name}
    runs = []  # consecutive above-threshold samples
    i = 0
    while i < len(scores):
        if above[i]:
            j = i
            while j + 1 < len(scores) and above[j + 1]:
                j += 1
            runs.append((i, j, float(scores[i:j + 1].max())))
            i = j + 1
        else:
            i += 1
    runs.sort(key=lambda r: -r[2])
    mismatch = front != model.front_end

    res["processing_status"] = "partial"  # video only; no audio model
    res["prediction"] = {
        "label": label,
        "score": r4(scores[peak]),
        "score_type": f"{model.name}_max_sample_sigmoid_uncalibrated",
        "decision_rule": (f"{model.name}: per-sample fall score = sigmoid(GRU over the last {F.T_WINDOW} samples at "
                          f"{F.SAMPLE_INTERVAL_S} s, {front} pose); fall if max score >= {thr} "
                          f"({model.summary.get('threshold_rule', 'threshold chosen on the validation split')})"),
        "granularity": "video",
    }
    res["signals"] = {
        "peak_score": r4(scores[peak]), "peak_pts_s": r4(pts[peak]), "threshold": thr,
        "samples": int(len(scores)), "samples_above_threshold": int(above.sum()),
        "fraction_above_threshold": r4(above.mean()),
        "pose_front_end": front, "pose_front_end_trained": model.front_end,
        "pose_front_end_note": (f"model trained on {model.front_end} poses; running on {front} poses is a front-end swap "
                                "(see MODEL_COMPARISON.md)") if mismatch else None,
        "score_note": "uncalibrated sigmoid output; each sample summarises the preceding 1.8 s (10 samples)",
        "person_detected": seen,
    }
    # decoded coverage vs container duration (a truncated upload must not look like a fully judged clip)
    if front == "mediapipe":
        frame_pts = arrays["pts_s"]
        last_decoded, n_dec, first_dec = float(frame_pts[-1]), len(frame_pts), float(frame_pts[0])
    else:
        last_decoded, n_dec, first_dec = float(ystats["last_pts_s"]), int(ystats["frames"]), float(ystats["first_pts_s"])
    frame_dt = (last_decoded - first_dec) / (n_dec - 1) if n_dec > 1 else 0.0
    expected = probe["video_duration_s"] or probe["duration_s"]
    clip_end = v_start + expected if expected else last_decoded
    video_reason = None if expected else "container has no duration; the clip end is the last decoded frame"
    if expected:
        covered = last_decoded - v_start + max(F.SAMPLE_INTERVAL_S, 1.5 * frame_dt)  # last frame starts one frame before the end
        if covered < 0.9 * expected:
            video_reason = (f"decoded only {covered:.2f} s of {expected:.2f} s (file may be truncated or corrupt); "
                            "time after the decoded range was not judged")
            clip_end = last_decoded
    res["evidence"] = [{"modality": "video", "source": src,
                        "time_range": {"start_pts_s": r4(v_start), "end_pts_s": r4(clip_end)},
                        "granularity": "whole_clip", "note": "video-level judgement = max over per-sample scores"}]
    if seen:
        res["evidence"].append({"modality": "pose", "source": src,
                                "time_range": {"start_pts_s": r4(pts[max(0, peak - F.T_WINDOW + 1)]), "end_pts_s": r4(pts[peak])},
                                "granularity": "window",
                                "note": f"causal window ending at the peak sample (score {scores[peak]:.4f}); not fall onset/end"})
    for a, b, mx in (runs[:MAX_WINDOW_EVIDENCE] if seen else []):
        res["evidence"].append({"modality": "pose", "source": src,
                                "time_range": {"start_pts_s": r4(pts[a]), "end_pts_s": r4(pts[b])},
                                "granularity": "window",
                                "note": f"{b - a + 1} consecutive samples >= {thr} (max {mx:.4f}); each sample looks back 1.8 s"})
    pose_metrics = {"samples_with_person": int(person.sum()), "person_fraction_samples": r4(person.mean()),
                    "torso_valid_fraction": r4((raw[:, 6] > 0).mean())}
    if frames_total is not None:
        pose_metrics.update(frames_processed=frames_total, frames_with_person=frames_person,
                            person_fraction_frames=r4(frames_person / frames_total) if frames_total else None)
    res["quality"] = {
        "video": {"available": True, "reason": video_reason, "stream_present": True,
                  "metrics": {"samples": int(len(pts)), "first_pts_s": r4(pts[0]), "last_pts_s": r4(pts[-1]),
                              "last_decoded_frame_pts_s": r4(last_decoded), "container_duration_s": r4(expected)}},
        "pose": {"available": seen,
                 "reason": ("no person detected in any sample: the label is not informative (empty scene, dark, occluded "
                            "or person out of view)") if not seen else
                           (None if person.mean() >= 0.5 else "person found in <50% of samples"),
                 "stream_present": True, "metrics": pose_metrics},
        "audio": {"available": False, "reason": "the fall model is video (pose) only; no audio head",
                  "stream_present": probe["audio_present"], "metrics": None},
    }
    s = model.summary
    res["model_version"] = {
        "pipeline": f"CareRelay pose-history GRU '{model.name}' (4,449 parameters)",
        "model_version": s.get("model_version"),
        "training_data": training_data_text(s),
        "training_summary": {k: s.get(k) for k in ("threshold", "threshold_from_validation", "threshold_rule", "loso_estimate",
                                                   "best_val_AP", "best_epoch", "weighted") if k in s},
        "weights": {"gru": {"file": rel(model.weights_path, args.weights_dir), "sha256": model.weights_sha256},
                    "pose": pose_info},
    }
    res["preprocessing_version"] = {
        "name": "carerelay-pose-gru-preproc/1",
        "pose_front_end": front,
        "front_end_settings": ({"running_mode": "VIDEO", "num_poses": 1, "frames": "every decoded frame, then sampled",
                                "keypoints": "COCO-17 subset of 33 landmarks; conf = visibility; box = landmark extent"}
                               if front == "mediapipe" else {**F.YOLO_POSE_SETTINGS, "frames": "sampled frames only",
                                                             "person": "highest detection confidence"}),
        "sampling": f"first decoded frame at or after every {F.SAMPLE_INTERVAL_S} s on the PTS timeline",
        "keypoint_confidence": F.KP_THRESHOLD,
        "features": F.FEATURE_NAMES,
        "normaliser": rel(model.normalizer_path, args.weights_dir),
        "window": f"causal, last {F.T_WINDOW} samples (shorter at clip start)",
        "time_source": "PTS = video stream start_time + OpenCV CAP_PROP_POS_MSEC",
    }
    res["runtime"] = {
        "device": "cpu" if front == "mediapipe" else args.device, "torch": torch.__version__,
        "torch_cuda_available": torch.cuda.is_available(), "torch_hip_version": getattr(torch.version, "hip", None),
        "opencv": cv2.__version__, "python": platform.python_version(), "platform": platform.platform(),
        "cpu_count": os.cpu_count(), "model_load_s": round(load_s, 3), "pose_wall_s": round(pose_s, 3),
        "inference_wall_s": round(infer_s, 3), "samples_per_s": round(len(pts) / infer_s, 2) if infer_s > 0 else None,
        "started_utc": started.isoformat(), "measured": True,
    }
    if args.samples_out:
        try:
            args.samples_out.parent.mkdir(parents=True, exist_ok=True)
            with args.samples_out.open("w", newline="") as f:
                wr = csv.writer(f)
                wr.writerow(["pts_s", *F.FEATURE_NAMES, "score", "above_threshold"])
                for t, x, sc in zip(pts, raw, scores):
                    wr.writerow([r4(t), *[None if not np.isfinite(v) else r4(v) for v in x], r4(sc), bool(sc >= thr)])
        except OSError as e:
            res["runtime"]["samples_out_error"] = f"{type(e).__name__}: {e}"
    return finish()


if __name__ == "__main__":
    sys.exit(main())
