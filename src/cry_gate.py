"""Local infant-cry presence gate.

The gate detects only an infant-cry-like audio event. It does not identify an
infant and does not infer a cause.
"""

from __future__ import annotations

import math
import threading
from pathlib import Path

import numpy as np
import soundfile as sf

try:
    from . import config
except ImportError:
    import config


_SAMPLE_RATE = 16000
_MAX_VIEW_SAMPLES = 160000
_INFANT_LABEL = "Baby cry, infant cry"
_GENERIC_CRY_LABEL = "Crying, sobbing"
_STRONG_INFANT_SCORE = 0.040
_BORDERLINE_INFANT_SCORE = 0.025
_GENERIC_DOMINANCE_RATIO = 1.20

_LOAD_LOCK = threading.Lock()
_WARM_LOCK = threading.Lock()
_EXTRACTOR = None
_MODEL = None
_WARMED = False


def _model_cache_dir() -> Path:
    """Return the cross-platform Hugging Face cache root for this model."""
    return Path(config.MODEL_DIR)


def _label_index(model, label: str) -> int:
    labels = getattr(getattr(model, "config", None), "id2label", {})
    for raw_index, candidate in labels.items():
        if candidate == label:
            return int(raw_index)
    raise RuntimeError(f"required AudioSet label missing: {label}")


def _load_pretrained(loader, cache_dir: Path):
    try:
        return loader.from_pretrained(
            config.CRY_GATE_MODEL_ID,
            cache_dir=str(cache_dir),
            local_files_only=True,
        )
    except (OSError, ValueError):
        return loader.from_pretrained(
            config.CRY_GATE_MODEL_ID,
            cache_dir=str(cache_dir),
            local_files_only=False,
        )


def _load_components():
    global _EXTRACTOR, _MODEL
    if _EXTRACTOR is not None and _MODEL is not None:
        return _EXTRACTOR, _MODEL

    with _LOAD_LOCK:
        if _EXTRACTOR is not None and _MODEL is not None:
            return _EXTRACTOR, _MODEL

        from transformers import (
            AutoFeatureExtractor,
            AutoModelForAudioClassification,
        )

        cache_dir = _model_cache_dir()
        cache_dir.mkdir(parents=True, exist_ok=True)
        extractor = _load_pretrained(AutoFeatureExtractor, cache_dir)
        model = _load_pretrained(AutoModelForAudioClassification, cache_dir)
        model.eval()
        _label_index(model, _INFANT_LABEL)
        _label_index(model, _GENERIC_CRY_LABEL)
        _EXTRACTOR = extractor
        _MODEL = model
        return _EXTRACTOR, _MODEL


def _event_scores(samples: np.ndarray) -> tuple[float, float]:
    import torch

    extractor, model = _load_components()
    inputs = extractor(
        samples,
        sampling_rate=_SAMPLE_RATE,
        return_tensors="pt",
    )
    with torch.inference_mode():
        logits = model(**inputs).logits[0]
        scores = torch.sigmoid(logits)
    infant_score = float(scores[_label_index(model, _INFANT_LABEL)].item())
    generic_score = float(scores[_label_index(model, _GENERIC_CRY_LABEL)].item())
    if not (math.isfinite(infant_score) and math.isfinite(generic_score)):
        raise RuntimeError("cry gate produced a non-finite score")
    return infant_score, generic_score


def warm() -> bool:
    """Load the cry gate and prove one extractor plus model forward pass works."""
    global _WARMED
    if _WARMED:
        return True

    with _WARM_LOCK:
        if _WARMED:
            return True
        try:
            _load_components()
            _event_scores(np.zeros(_SAMPLE_RATE, dtype=np.float32))
        except Exception:
            return False
        _WARMED = True
        return True


def readiness() -> dict[str, object]:
    """Return the public, score-free readiness state."""
    return {
        "ready": warm(),
        "model_version": config.CRY_GATE_MODEL_VERSION,
    }


def _decision(
    status: str,
    reason_code: str,
    infant_score: float,
    generic_score: float,
    duration_s: float,
) -> dict[str, object]:
    return {
        "status": status,
        "label": (
            "Infant-cry-like sound detected"
            if status == "infant_cry_detected"
            else None
        ),
        "reason_codes": [reason_code],
        "analyzed_duration_s": round(duration_s, 3),
        "analysis_view_count": 1,
        "model_version": config.CRY_GATE_MODEL_VERSION,
        "_infant_score": float(infant_score),
        "_generic_cry_score": float(generic_score),
    }


def _invalid_audio() -> dict[str, object]:
    return _decision(
        "invalid_audio",
        "cry_gate_invalid_audio",
        0.0,
        0.0,
        0.0,
    )


def classify(audio_path: str) -> dict[str, object]:
    """Classify one canonical 16 kHz mono WAV and fail closed on model errors."""
    try:
        path = Path(audio_path)
    except (TypeError, ValueError):
        return _invalid_audio()
    if path.suffix.casefold() != ".wav" or not path.is_file():
        return _invalid_audio()

    try:
        samples, sample_rate = sf.read(
            str(path),
            dtype="float32",
            always_2d=False,
        )
    except (OSError, RuntimeError, ValueError, TypeError):
        return _invalid_audio()

    samples = np.asarray(samples)
    if samples.ndim != 1 or samples.size == 0 or sample_rate != _SAMPLE_RATE:
        return _invalid_audio()

    view_size = min(samples.size, _MAX_VIEW_SAMPLES)
    start = (samples.size - view_size) // 2
    view = samples[start : start + view_size]
    duration_s = view.size / _SAMPLE_RATE

    try:
        infant_score, generic_score = _event_scores(view)
    except Exception:
        return _decision(
            "gate_unavailable",
            "cry_gate_model_unavailable",
            0.0,
            0.0,
            duration_s,
        )

    if (
        infant_score >= _STRONG_INFANT_SCORE
        and infant_score >= _GENERIC_DOMINANCE_RATIO * generic_score
    ):
        return _decision(
            "infant_cry_detected",
            "infant_cry_evidence_strong",
            infant_score,
            generic_score,
            duration_s,
        )
    if infant_score >= _BORDERLINE_INFANT_SCORE:
        reason = (
            "generic_cry_not_infant_specific"
            if infant_score < _GENERIC_DOMINANCE_RATIO * generic_score
            else "infant_cry_evidence_borderline"
        )
        return _decision(
            "cry_uncertain",
            reason,
            infant_score,
            generic_score,
            duration_s,
        )
    return _decision(
        "no_cry_detected",
        "infant_cry_evidence_low",
        infant_score,
        generic_score,
        duration_s,
    )
