"""Run the three controlled infant recordings through the real care pipeline."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src import (  # noqa: E402
    audio_ingest,
    care_sessions,
    cry_gate,
    encoders,
    identity,
    store,
)


DEFAULT_ASSET_ROOT = (
    REPO_ROOT / "demo_assets" / "baby_audio" / "warning-demo"
)
MINIMUM_LISTENING_SECONDS = 20
CASES = (
    (
        "x4",
        "demo-baby-x4-extended-playback.wav",
        "bottle",
    ),
    (
        "x7",
        "demo-baby-x7-extended-playback.wav",
        "upright",
    ),
    (
        "x8",
        "demo-baby-x8-extended-playback.wav",
        "white noise",
    ),
)


def _segments(source: Path, output: Path, seconds: int) -> list[Path]:
    output.mkdir(parents=True, exist_ok=True)
    pattern = output / "segment-%03d.wav"
    completed = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-i",
            str(source),
            "-f",
            "segment",
            "-segment_time",
            str(seconds),
            "-c:a",
            "pcm_s16le",
            str(pattern),
        ],
        capture_output=True,
        check=False,
        timeout=180,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"could not segment {source.name}")
    return sorted(output.glob("segment-*.wav"))


def _demo_profile(database: str) -> dict:
    matches = [
        profile
        for profile in identity.list_profiles(database)
        if profile.get("display_name") == "Demo Baby"
        and profile.get("kind") == identity.KIND_INFANT
        and profile.get("status") == "ready"
    ]
    if len(matches) != 1:
        raise RuntimeError("exactly one ready Demo Baby profile is required")
    return matches[0]


def _warm_models() -> None:
    encoder = identity.ENCODER_FOR_KIND[identity.KIND_INFANT]
    warmed = encoders.warm([encoder])
    if not warmed.get(encoder):
        raise RuntimeError(
            f"the infant identity encoder is unavailable: {encoder}"
        )
    if not cry_gate.warm():
        raise RuntimeError("the infant cry detector is unavailable")


def _meets_minimum_listening_window(
    segments_processed: int,
    segment_seconds: int,
) -> bool:
    return segments_processed * segment_seconds >= MINIMUM_LISTENING_SECONDS


def run(
    *,
    database: str,
    data_root: Path,
    asset_root: Path = DEFAULT_ASSET_ROOT,
    segment_seconds: int = 3,
    maximum_segments: int = 16,
) -> dict:
    store.init_db(database)
    profile = _demo_profile(database)
    _warm_models()
    cases = []
    for label, filename, expected_phrase in CASES:
        source = asset_root / filename
        if not source.is_file():
            raise RuntimeError(f"missing controlled recording: {source}")
        care_session = care_sessions.create(profile["id"], db_path=database)
        if care_session.get("status") == "error":
            raise RuntimeError(f"could not create the {label} care session")
        observations = []
        decision = None
        with tempfile.TemporaryDirectory(prefix=f"soothetrace-{label}-") as temporary:
            segment_paths = _segments(
                source,
                Path(temporary),
                segment_seconds,
            )
            for sequence, segment_path in enumerate(
                segment_paths[:maximum_segments],
                start=1,
            ):
                started = time.monotonic()
                ingested = audio_ingest.ingest_audio(
                    segment_path.read_bytes(),
                    "audio/wav",
                    capture_metadata={
                        "capture_source": "controlled_release_acceptance",
                        "source_case": label,
                    },
                    storage_root=data_root / label,
                )
                result = care_sessions.submit_chunk(
                    care_session["id"],
                    sequence,
                    ingested,
                    database,
                )
                chunk = result.get("chunk") or {}
                session = result.get("session") or {}
                progress = chunk.get("decision_progress") or {}
                observations.append(
                    {
                        "sequence": sequence,
                        "status": chunk.get("status"),
                        "cry_status": (
                            chunk.get("cry_presence") or {}
                        ).get("status"),
                        "additional_confirmations": progress.get(
                            "additional_confirmations"
                        ),
                        "required_additional_confirmations": progress.get(
                            "required_additional_confirmations"
                        ),
                        "processing_seconds": round(
                            time.monotonic() - started,
                            3,
                        ),
                    }
                )
                if session.get("decision"):
                    decision = session["decision"]
                    break
        recommendation = (
            (decision.get("guidance") or {}).get("recommendation")
            if isinstance(decision, dict)
            else None
        )
        audio_seconds_processed = len(observations) * segment_seconds
        passed = (
            isinstance(recommendation, str)
            and expected_phrase.casefold() in recommendation.casefold()
            and _meets_minimum_listening_window(
                len(observations),
                segment_seconds,
            )
        )
        cases.append(
            {
                "case": label,
                "source": filename,
                "expected_phrase": expected_phrase,
                "latched": decision is not None,
                "recommendation": recommendation,
                "passed": passed,
                "segments_processed": len(observations),
                "audio_seconds_processed": audio_seconds_processed,
                "observations": observations,
            }
        )
    recommendations = {
        item["recommendation"] for item in cases if item["recommendation"]
    }
    passed = all(item["passed"] for item in cases) and len(recommendations) == 3
    return {
        "status": "passed" if passed else "failed",
        "profile": {
            "id": profile["id"],
            "display_name": profile["display_name"],
        },
        "segment_seconds": segment_seconds,
        "minimum_listening_seconds": MINIMUM_LISTENING_SECONDS,
        "required_cases": len(CASES),
        "distinct_recommendations": len(recommendations),
        "cases": cases,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify the controlled three-outcome SootheTrace demo."
    )
    parser.add_argument("--db", required=True)
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--asset-root", default=str(DEFAULT_ASSET_ROOT))
    parser.add_argument("--segment-seconds", type=int, default=3)
    parser.add_argument("--maximum-segments", type=int, default=16)
    parser.add_argument("--json")
    args = parser.parse_args(argv)
    try:
        result = run(
            database=str(Path(args.db).expanduser().resolve()),
            data_root=Path(args.data_root).expanduser().resolve(),
            asset_root=Path(args.asset_root).expanduser().resolve(),
            segment_seconds=args.segment_seconds,
            maximum_segments=args.maximum_segments,
        )
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"Core demo acceptance failed: {exc}", file=sys.stderr)
        return 1
    rendered = json.dumps(result, indent=2)
    print(rendered)
    if args.json:
        Path(args.json).write_text(rendered + "\n", encoding="utf-8")
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
