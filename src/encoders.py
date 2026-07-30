"""Encoder registry - swappable acoustic embeddings behind one call. Owned by acoustics workstream.

`identity.py` never knows which encoder it is using. That matters because the engineered
87-dim fingerprint is already good enough to demo (13/15 correct, 0 wrong on live audio),
so a learned encoder is an *upgrade path*, never a dependency. If a download fails or a
model disappoints, the system keeps working.

⚠️ NORMALIZATION IS ENCODER-SPECIFIC, and getting this wrong is silent:

* **mfcc87-v1** - hand-engineered statistics. MUST be z-scored against a population baseline
  before cosine. On raw vectors a DIFFERENT baby scored +0.9999 while a file matched ITSELF
  at +0.9915 (docs/FINDINGS.md §5).
* **ECAPA embeddings** - trained with a cosine/AAM objective, so the geometry is already
  correct. They need L2 only. z-scoring them against a corpus of *cry* statistics would
  distort a space that was learned to be compared directly.

So each encoder declares how it wants to be compared, rather than the caller assuming.
"""
from __future__ import annotations

import os

import numpy as np

try:
    from . import fingerprint
except ImportError:
    import fingerprint

MFCC87 = "mfcc87-v1"
ECAPA_CRY = "ecapa-cryceleb-v1"
ECAPA_ADULT = "ecapa-voxceleb-v1"

_HF_SOURCES = {
    ECAPA_CRY: "Ubenwa/ecapa-voxceleb-ft2-cryceleb",     # fine-tuned for INFANT cry verification
    ECAPA_ADULT: "speechbrain/spkrec-ecapa-voxceleb",    # adult speech; for human imitations
}

# Licences, recorded because a commercial wrapper would need a review (docs/LIABILITY.md).
LICENCES = {
    MFCC87: "none (our own code)",
    ECAPA_CRY: "CC-BY-SA-4.0 (CryCeleb dataset CC-BY-NC-ND-4.0)",
    ECAPA_ADULT: "Apache-2.0",
}

MODEL_CACHE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "models")

_loaded: dict[str, object] = {}


def available() -> list[str]:
    """Encoders that can actually run right now."""
    out = [MFCC87]
    try:
        import speechbrain  # noqa: F401
        import torch        # noqa: F401
        out += [ECAPA_CRY, ECAPA_ADULT]
    except ImportError:
        pass
    return out


def needs_baseline(name: str) -> bool:
    """True when the encoder must be z-scored against a population baseline."""
    return name == MFCC87


def dim(name: str) -> int | None:
    return fingerprint.DIM if name == MFCC87 else 192   # ECAPA-TDNN emits 192-d


def _load(name: str):
    """Lazy-load and cache. Loading is slow, so a long-running server should call
    `warm()` at startup rather than paying this on the first request."""
    if name in _loaded:
        return _loaded[name]
    if name not in _HF_SOURCES:
        raise ValueError(f"unknown encoder {name}")
    from speechbrain.inference.speaker import EncoderClassifier
    os.makedirs(MODEL_CACHE, exist_ok=True)
    model = EncoderClassifier.from_hparams(
        source=_HF_SOURCES[name],
        savedir=os.path.join(MODEL_CACHE, name),
        run_opts={"device": "cpu"},   # deterministic; MPS gave no win at this clip length
    )
    _loaded[name] = model
    return model


def warm(names: list[str] | None = None) -> dict[str, bool]:
    """Preload models. Call once at server startup - see docs/WEBAPP.md."""
    out = {}
    for n in (names or available()):
        if n == MFCC87:
            out[n] = True
            continue
        try:
            _load(n)
            out[n] = True
        except Exception:                                        # noqa: BLE001
            out[n] = False
    return out


def encode(name: str, wav_path: str) -> list[float] | None:
    """One recording → one embedding. None when the audio is unusable.

    Never raises: a failed encode must degrade, not crash a session
    (docs/CONTRACTS.md rule 6).
    """
    if name == MFCC87:
        return fingerprint.compute_windowed(wav_path)
    try:
        import torch
        y = fingerprint.load_audio(wav_path)        # 16 kHz mono float32, via ffmpeg
        if y is None or len(y) < fingerprint.SR * 0.3:
            return None
        model = _load(name)
        with torch.no_grad():
            emb = model.encode_batch(torch.from_numpy(y).unsqueeze(0))
        v = emb.squeeze().cpu().numpy().astype(np.float64)
        if v.ndim != 1 or not np.all(np.isfinite(v)):
            return None
        return [float(x) for x in v]
    except Exception:                                            # noqa: BLE001
        return None


def prepare(name: str, vecs, baseline=None) -> np.ndarray:
    """Put embeddings into the space where cosine is meaningful FOR THIS ENCODER.

    mfcc87  -> z-score against (mu, sd), then L2   [mandatory, see module docstring]
    ECAPA   -> L2 only                             [the objective already did the work]
    """
    X = np.atleast_2d(np.asarray(vecs, dtype=np.float64))
    if needs_baseline(name):
        if baseline is None:
            raise ValueError(f"{name} requires a population baseline")
        mu, sd = baseline
        X = (X - mu) / (sd + 1e-9)
    return X / (np.linalg.norm(X, axis=1, keepdims=True) + 1e-9)
