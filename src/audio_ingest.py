"""Managed browser-audio ingest for identity and incident evidence.

The source upload and canonical raw WAV are immutable evidence. Identity uses a separate WAV
created with one constant gain; no compression, limiting, filtering, or pitch processing occurs.
"""

from __future__ import annotations

import hashlib
import math
import subprocess
import uuid
import wave
from pathlib import Path

import numpy as np

try:
    from . import config, fingerprint
except ImportError:
    import config
    import fingerprint


MAX_UPLOAD_BYTES = 64 * 1024 * 1024
TARGET_RMS_DB = -24.0
MAX_NORMALIZED_PEAK_DB = -1.0

_MIME_EXTENSIONS = {
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/mp4": ".m4a",
    "audio/mp4;codecs=mp4a.40.2": ".m4a",
    "audio/x-m4a": ".m4a",
    "audio/mpeg": ".mp3",
    "audio/aac": ".aac",
    "audio/flac": ".flac",
    "video/mp4": ".mp4",
    "audio/webm": ".webm",
    "audio/webm;codecs=opus": ".webm",
    "audio/ogg": ".ogg",
    "audio/ogg;codecs=opus": ".ogg",
}


def _normalized_mime(value: str) -> str:
    if not isinstance(value, str):
        return ""
    return ";".join(part.strip() for part in value.casefold().split(";"))


def _safe_capture_id(value: str | None) -> str:
    try:
        parsed = uuid.UUID(value) if value else None
    except (ValueError, AttributeError, TypeError):
        parsed = None
    return str(parsed or uuid.uuid4())


def _read_pcm16(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as handle:
        if handle.getnchannels() != 1 or handle.getsampwidth() != 2:
            raise ValueError("canonical WAV must be mono PCM16")
        sample_rate = handle.getframerate()
        frames = handle.readframes(handle.getnframes())
    samples = np.frombuffer(frames, dtype="<i2").astype(np.float64) / 32768.0
    return samples, sample_rate


def _write_pcm16(path: Path, samples: np.ndarray, sample_rate: int) -> None:
    pcm = np.round(samples * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(pcm.tobytes())


def _db(value: float) -> float:
    return 20.0 * math.log10(max(value, 1e-12))


def _invalid(reason: str, **details) -> dict:
    return {"status": "invalid", "reason": reason, **details}


def ingest_audio(
    payload: bytes,
    mime: str,
    capture_metadata: dict | None = None,
    upload_id: str | None = None,
    storage_root: str | Path | None = None,
) -> dict:
    """Persist, decode, measure, and linearly normalize an untrusted browser upload.

    Returns a structured invalid state on every failure and never raises.
    """
    if not isinstance(payload, (bytes, bytearray, memoryview)) or not payload:
        return _invalid("empty_upload")
    if len(payload) > MAX_UPLOAD_BYTES:
        return _invalid("upload_too_large")

    normalized_mime = _normalized_mime(mime)
    extension = _MIME_EXTENSIONS.get(normalized_mime)
    if extension is None:
        return _invalid("unsupported_mime")

    capture_id = _safe_capture_id(upload_id)
    audio_root = Path(storage_root) if storage_root is not None else Path(config.AUDIO_DIR)
    managed_root = audio_root.resolve() / "managed"
    capture_dir = managed_root / capture_id
    if capture_dir.exists():
        capture_dir = managed_root / str(uuid.uuid4())

    source_path = capture_dir / f"source{extension}"
    canonical_path = capture_dir / "canonical.wav"
    identity_path = capture_dir / "identity.wav"

    try:
        capture_dir.mkdir(parents=True, mode=0o700)
        source_path.write_bytes(bytes(payload))
    except OSError:
        return _invalid("storage_failed")

    source_details = {
        "source_path": str(source_path),
        "sha256": hashlib.sha256(bytes(payload)).hexdigest(),
    }
    try:
        completed = subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-y",
                "-i",
                str(source_path),
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-c:a",
                "pcm_s16le",
                str(canonical_path),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=180,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return _invalid("decoder_unavailable", **source_details)

    if completed.returncode != 0 or not canonical_path.is_file():
        canonical_path.unlink(missing_ok=True)
        return _invalid("decode_failed", **source_details)

    canonical_details = {**source_details, "canonical_path": str(canonical_path)}
    try:
        samples, sample_rate = _read_pcm16(canonical_path)
        if sample_rate != 16000 or samples.size == 0:
            return _invalid("empty_decoded_audio", **canonical_details)

        rms = math.sqrt(float(np.mean(np.square(samples, dtype=np.float64))))
        peak = float(np.max(np.abs(samples)))
        if not math.isfinite(rms) or rms <= 1e-9:
            return _invalid("near_silence", **canonical_details)

        target_rms = 10.0 ** (TARGET_RMS_DB / 20.0)
        gain = target_rms / rms
        predicted_peak = peak * gain
        max_peak = 10.0 ** (MAX_NORMALIZED_PEAK_DB / 20.0)
        if not math.isfinite(predicted_peak) or predicted_peak > max_peak:
            return _invalid(
                "unsafe_normalization_headroom",
                **canonical_details,
                quality={
                    "duration_s": round(samples.size / sample_rate, 6),
                    "mean_db": round(_db(rms), 4),
                    "peak_db": round(_db(peak), 4),
                    "predicted_normalized_peak_db": round(_db(predicted_peak), 4),
                },
            )

        normalized = samples * gain
        _write_pcm16(identity_path, normalized, sample_rate)
        written, _ = _read_pcm16(identity_path)
        normalized_rms = math.sqrt(float(np.mean(np.square(written, dtype=np.float64))))
        normalized_peak = float(np.max(np.abs(written)))
        try:
            voiced_fraction = float(fingerprint._voiced_mask(samples).mean())
        except Exception:
            voiced_fraction = 0.0

        return {
            "status": "ready",
            **canonical_details,
            "identity_path": str(identity_path),
            "quality": {
                "duration_s": round(samples.size / sample_rate, 6),
                "mean_db": round(_db(rms), 4),
                "peak_db": round(_db(peak), 4),
                "voiced_fraction": round(voiced_fraction, 6),
                "gain_db": round(_db(gain), 4),
                "normalized_mean_db": round(_db(normalized_rms), 4),
                "normalized_peak_db": round(_db(normalized_peak), 4),
            },
            "capture": dict(capture_metadata) if isinstance(capture_metadata, dict) else {},
            "versions": {
                "decode": "ffmpeg-pcm16-v1",
                "normalization": "rms-24db-v1",
            },
        }
    except (OSError, ValueError, wave.Error, FloatingPointError):
        identity_path.unlink(missing_ok=True)
        return _invalid("decoded_audio_invalid", **canonical_details)
