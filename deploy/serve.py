"""Fixed release entry point. Validates configuration, then starts the family site.

The release container includes English Whisper on CPU; text/photo inference uses
the team's AMD Token Factory endpoint. No credentials are printed or stored here.
"""
from __future__ import annotations

import os
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]


def validate_verifier_config(env: dict) -> None:
    """Validate optional configuration without loading weights or making network calls.

    Artifact hashes and model compatibility are checked again by the runtime loader.
    A full model's validation operating point is an engineering gate, not clinical validation.
    """
    mode = env.get("KINDRED_VERIFIER_MODE", "off").lower()
    if mode not in ("off", "shadow", "gate"):
        raise ValueError("KINDRED_VERIFIER_MODE must be off, shadow or gate")
    if mode == "off":
        return
    try:
        threads = int(env.get("KINDRED_VERIFIER_THREADS", "2"))
    except (TypeError, ValueError):
        raise ValueError("KINDRED_VERIFIER_THREADS must be a positive integer") from None
    if threads < 1:
        raise ValueError("KINDRED_VERIFIER_THREADS must be a positive integer")
    bundle = env.get("KINDRED_VERIFIER_DIR", "").strip()
    if not bundle:
        raise ValueError("Set KINDRED_VERIFIER_DIR when the verifier is enabled")
    try:
        card = json.loads((Path(bundle) / "verifier.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise ValueError("KINDRED_VERIFIER_DIR must contain a readable verifier.json") from None
    if not isinstance(card, dict):
        raise ValueError("verifier.json must contain an object")
    if mode == "gate" and (card.get("stage") != "full" or card.get("validation_operating_point_found") is not True):
        raise ValueError("Gate requires a full model with a useful validation operating point; use shadow first")


def command(env: dict) -> list[str]:
    port = env.get("PORT", "8501")
    if not port.isdigit() or not 1 <= int(port) <= 65535:
        raise ValueError("PORT must be an integer between 1 and 65535")
    validate_verifier_config(env)
    if env.get("CARERELAY_REQUIRE_LIVE", "1") != "0":
        names = ("CARERELAY_LLM_BASE_URL", "CARERELAY_LLM_MODEL", "CARERELAY_PHOTO_MODEL", "CARERELAY_LLM_API_KEY")
        missing = [k for k in names if not env.get(k, "").strip()]
        if missing:
            raise ValueError("Set these deployment variables: " + ", ".join(missing))
    # The app shell: the family timeline is its default page, beside the scorecard and AMD Runtime pages. It lives
    # under ui/pages/ because Dockerfile.release copies only that folder of ui/.
    return [sys.executable, "-m", "streamlit", "run",
            str(ROOT / "handoff_day1/ui/pages/shell/kindred_app.py"),
            "--server.address", "0.0.0.0", "--server.port", port,
            "--server.headless", "true", "--browser.gatherUsageStats", "false",
            "--server.maxUploadSize", "25"]


def main() -> None:
    try:
        args = command(os.environ)
        if os.environ.get("CARERELAY_REQUIRE_ASR", "1") != "0":
            sys.path.insert(0, str(ROOT / "handoff_day1/agent"))
            from asr_local import missing
            absent = missing()
            if absent:
                raise ValueError("Speech dependencies missing: " + ", ".join(absent) + ". Build Dockerfile.release.")
    except ValueError as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(2)
    version = (ROOT / "handoff_day1/RELEASE_VERSION.txt").read_text(encoding="utf-8").strip()
    print("Starting " + version + " (family timeline)", flush=True)
    os.execv(sys.executable, args)


if __name__ == "__main__":
    main()
