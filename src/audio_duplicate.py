"""Private content signatures used to avoid counting one clip repeatedly."""

from __future__ import annotations

import math
import wave
from pathlib import Path

import numpy as np


VERSION = "temporal-spectral-96-v1"
DIMENSION = 96
NEAR_DUPLICATE_THRESHOLD = 0.985
MINIMUM_SECONDS = 0.5


def _read_pcm16(path: str | Path) -> tuple[np.ndarray, int] | None:
    try:
        with wave.open(str(path), "rb") as source:
            if (
                source.getnchannels() != 1
                or source.getsampwidth() != 2
                or source.getcomptype() != "NONE"
            ):
                return None
            rate = source.getframerate()
            frames = source.readframes(source.getnframes())
    except (OSError, EOFError, wave.Error):
        return None
    if rate <= 0 or not frames:
        return None
    samples = np.frombuffer(frames, dtype="<i2").astype(np.float64) / 32768.0
    return samples, rate


def _normalized(values: np.ndarray) -> np.ndarray | None:
    if values.size == 0 or not np.all(np.isfinite(values)):
        return None
    centered = values - float(values.mean())
    scale = float(centered.std())
    if not math.isfinite(scale) or scale < 1e-9:
        return None
    return centered / scale


def signature(path: str | Path) -> list[float] | None:
    """Return a level-robust temporal and spectral signature for canonical WAV."""
    decoded = _read_pcm16(path)
    if decoded is None:
        return None
    samples, sample_rate = decoded
    if samples.size < sample_rate * MINIMUM_SECONDS:
        return None
    peak = float(np.max(np.abs(samples)))
    if not math.isfinite(peak) or peak < 1e-6:
        return None
    samples = samples / peak

    envelope = []
    for segment in np.array_split(samples, 32):
        rms = math.sqrt(float(np.mean(np.square(segment))) + 1e-12)
        envelope.append(math.log(rms + 1e-9))
    envelope_vector = _normalized(np.asarray(envelope, dtype=np.float64))
    if envelope_vector is None:
        return None

    band_edges = np.geomspace(150.0, min(4000.0, sample_rate / 2), 9)
    spectral = []
    for segment in np.array_split(samples, 8):
        if segment.size < 64:
            return None
        windowed = segment * np.hanning(segment.size)
        power = np.square(np.abs(np.fft.rfft(windowed)))
        frequencies = np.fft.rfftfreq(segment.size, 1.0 / sample_rate)
        for lower, upper in zip(band_edges[:-1], band_edges[1:]):
            selected = power[(frequencies >= lower) & (frequencies < upper)]
            energy = float(selected.mean()) if selected.size else 0.0
            spectral.append(math.log(energy + 1e-12))
    spectral_vector = _normalized(np.asarray(spectral, dtype=np.float64))
    if spectral_vector is None:
        return None

    combined = np.concatenate((envelope_vector, spectral_vector))
    norm = float(np.linalg.norm(combined))
    if combined.size != DIMENSION or not math.isfinite(norm) or norm < 1e-9:
        return None
    return [float(value) for value in combined / norm]


def similarity(first, second) -> float | None:
    try:
        left = np.asarray(first, dtype=np.float64)
        right = np.asarray(second, dtype=np.float64)
    except (TypeError, ValueError):
        return None
    if (
        left.shape != (DIMENSION,)
        or right.shape != (DIMENSION,)
        or not np.all(np.isfinite(left))
        or not np.all(np.isfinite(right))
    ):
        return None
    denominator = float(np.linalg.norm(left) * np.linalg.norm(right))
    if denominator < 1e-12:
        return None
    return float(np.dot(left, right) / denominator)


def is_near_duplicate(
    first,
    second,
    *,
    threshold: float = NEAR_DUPLICATE_THRESHOLD,
) -> bool:
    score = similarity(first, second)
    return score is not None and score >= threshold
