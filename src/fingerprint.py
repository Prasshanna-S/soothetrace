"""Acoustic fingerprinting. Owned by acoustics workstream - see docs/CONTRACTS.md.

Port of the validated reference implementation in experiments/feats.py. Every number in
docs/FINDINGS.md came from that code path, so this file must stay behaviourally identical
to it - if you change the feature layout, the measured results no longer describe this code.

⚠️ Callers must NEVER cosine raw fingerprints. Normalization is mandatory and lives in
retrieve.py. On raw vectors a DIFFERENT baby scored +0.9999 while a file matched itself at
+0.9915 - everything matches everything. docs/FINDINGS.md §5.

No network calls in this module (docs/CONTRACTS.md rule 7). numpy + scipy only - librosa's
numba/llvmlite dependency will not build on Python 3.12 / macOS ARM.
"""
from __future__ import annotations

import os
import subprocess
from datetime import datetime

import numpy as np
from scipy.fftpack import dct

try:
    from . import config
except ImportError:  # allow `python src/fingerprint.py` and flat imports
    import config

SR = config.SAMPLE_RATE

# 20 MFCC means | 20 MFCC SDs | 20 delta means | 20 delta SDs
# | F0 mean/SD/p10/p90 | centroid mean/SD | voiced fraction
DIM = 87

_N_MFCC = 20
_N_FFT = 512
_HOP = 160
_MIN_VOICED_S = 0.3


# ---------------------------------------------------------------- audio I/O

def load_audio(path: str, sr: int = SR):
    """Mono float32 at `sr` via ffmpeg. Accepts any format ffmpeg can read.

    Returns None rather than raising if the file is missing or undecodable - 
    nothing in this codebase may crash mid-demo (docs/CONTRACTS.md rule 6).
    """
    if not path or not os.path.exists(path):
        return None
    try:
        p = subprocess.run(
            ["ffmpeg", "-v", "quiet", "-i", path,
             "-f", "f32le", "-ac", "1", "-ar", str(sr), "-"],
            capture_output=True,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if p.returncode != 0 or not p.stdout:
        return None
    return np.frombuffer(p.stdout, dtype=np.float32).copy()


def duration_s(path: str) -> float | None:
    """Wall-clock duration in seconds, or None."""
    y = load_audio(path)
    return None if y is None else len(y) / SR


# ------------------------------------------------------------ feature stack

def _mel_fb(n_filt: int = 40, n_fft: int = _N_FFT, sr: int = SR):
    hi = 2595 * np.log10(1 + (sr / 2) / 700)
    pts = np.linspace(0.0, hi, n_filt + 2)
    hz = 700 * (10 ** (pts / 2595) - 1)
    bins = np.floor((n_fft + 1) * hz / sr).astype(int)
    fb = np.zeros((n_filt, n_fft // 2 + 1))
    for m in range(1, n_filt + 1):
        l, c, r = bins[m - 1], bins[m], bins[m + 1]
        if c == l:
            c = l + 1
        if r == c:
            r = c + 1
        if r >= fb.shape[1]:
            r = fb.shape[1] - 1
        if c >= r:
            continue
        fb[m - 1, l:c] = (np.arange(l, c) - l) / max(c - l, 1)
        fb[m - 1, c:r] = (r - np.arange(c, r)) / max(r - c, 1)
    return fb


_FB = _mel_fb()


def _frames(y, n_fft: int = _N_FFT, hop: int = _HOP):
    if len(y) < n_fft:
        return np.zeros((0, n_fft))
    idx = np.arange(0, len(y) - n_fft, hop)
    if len(idx) == 0:
        return np.zeros((0, n_fft))
    return np.stack([y[i:i + n_fft] for i in idx]) * np.hamming(n_fft)


def _logmel(y):
    f = _frames(y)
    if len(f) == 0:
        return np.zeros((0, _FB.shape[0]))
    spec = np.abs(np.fft.rfft(f, axis=1)) ** 2
    return np.log(spec @ _FB.T + 1e-10)


def _mfcc(y, n: int = _N_MFCC):
    lm = _logmel(y)
    if len(lm) == 0:
        return np.zeros((0, n))
    return dct(lm, type=2, axis=1, norm="ortho")[:, :n]


def _f0_track(y, sr: int = SR, fmin: int = 150, fmax: int = 900):
    """Autocorrelation F0. Infant cries measured at median ~432 Hz (FINDINGS §3)."""
    win, hop = 1024, 256
    out = []
    for i in range(0, max(len(y) - win, 0), hop):
        w = y[i:i + win] * np.hanning(win)
        if np.sqrt((w ** 2).mean()) < 1e-3:
            continue
        w = w - w.mean()
        ac = np.correlate(w, w, "full")[win - 1:]
        lo, hi = int(sr / fmax), int(sr / fmin)
        if hi >= len(ac) or ac[0] <= 0:
            continue
        seg = ac[lo:hi]
        if len(seg) == 0:
            continue
        pk = int(np.argmax(seg)) + lo
        if ac[pk] / ac[0] > 0.3:
            out.append(sr / pk)
    return np.array(out)


def _voiced_mask(y, thresh_db: float = -32.0):
    """Energetic (crying/speaking) frames only - drops silence and room tone."""
    win, hop = 512, _HOP
    keep = np.zeros(len(y), bool)
    for i in range(0, max(len(y) - win, 0), hop):
        rms = np.sqrt((y[i:i + win] ** 2).mean() + 1e-12)
        if 20 * np.log10(rms + 1e-12) > thresh_db:
            keep[i:i + win] = True
    return keep


def _fingerprint_array(y):
    """Core 87-dim vector from a float32 mono waveform, or None."""
    if y is None or len(y) < SR * _MIN_VOICED_S:
        return None
    m = _voiced_mask(y)
    if m.sum() < SR * _MIN_VOICED_S:
        return None
    yv = y[m]
    mc = _mfcc(yv)
    if len(mc) < 5:
        return None
    d = np.diff(mc, axis=0)
    f0 = _f0_track(yv)
    f0s = ([f0.mean(), f0.std(), np.percentile(f0, 10), np.percentile(f0, 90)]
           if len(f0) > 3 else [0.0, 0.0, 0.0, 0.0])
    lm = _logmel(yv)
    if len(lm):
        cent = (lm * np.arange(lm.shape[1])).sum(1) / (lm.sum(1) + 1e-9)
    else:
        cent = np.zeros(1)
    v = np.concatenate([
        mc.mean(0), mc.std(0), d.mean(0), d.std(0),
        f0s, [cent.mean(), cent.std()], [float(m.mean())],
    ])
    if v.shape[0] != DIM or not np.all(np.isfinite(v)):
        return None
    return v.astype(np.float32)


# --------------------------------------------------------------- public API

def compute(wav_path: str) -> list[float] | None:
    """87-dim UN-normalized fingerprint of a recording, or None.

    Returns None when there is under 0.3 s of voiced audio - the caller must treat that
    as "no usable signal", not as a zero vector.

    ⚠️ Pass the RAW MIXTURE. Do not pre-separate caregiver from infant audio: measured,
    separation drops the cosine to +0.031 (no better than a stranger's cry) and also
    truncates the transcript. docs/FINDINGS.md §3.
    """
    v = _fingerprint_array(load_audio(wav_path))
    return None if v is None else [float(x) for x in v]


def compute_windowed(wav_path: str, window_s: float = 1.5,
                     hop_s: float = 0.75) -> list[float] | None:
    """Episode-level fingerprint: mean of per-window fingerprints.

    This is the unit that was validated for retrieval - 30.5% top-1 against 0.7% chance
    over 421 episodes / 207 babies, vs 22.0% when matching single windows
    (docs/FINDINGS.md §2). Prefer this over compute() for anything stored.
    Falls back to compute() for recordings shorter than one window.
    """
    y = load_audio(wav_path)
    if y is None:
        return None
    seg, hop = int(window_s * SR), int(hop_s * SR)
    if len(y) < seg:
        return compute(wav_path)
    vs = [_fingerprint_array(y[s:s + seg]) for s in range(0, len(y) - seg + 1, hop)]
    vs = [v for v in vs if v is not None]
    if not vs:
        return None
    return [float(x) for x in np.mean(vs, axis=0)]


    # ---------------------------------------------------------------- CMN variant

DIM_CMN = 64


def _fingerprint_cmn_array(y):
    """Channel-robust variant. 64 dims. See compute_cmn() for the reasoning."""
    if y is None or len(y) < SR * _MIN_VOICED_S:
        return None
    m = _voiced_mask(y)
    if m.sum() < SR * _MIN_VOICED_S:
        return None
    yv = y[m]
    mc = _mfcc(yv)
    if len(mc) < 5:
        return None
    d = np.diff(mc, axis=0)
    f0 = _f0_track(yv)
    f0s = ([f0.mean(), f0.std(), np.percentile(f0, 10), np.percentile(f0, 90)]
           if len(f0) > 3 else [0.0, 0.0, 0.0, 0.0])
    v = np.concatenate([mc.std(0), d.mean(0), d.std(0), f0s])
    if v.shape[0] != DIM_CMN or not np.all(np.isfinite(v)):
        return None
    return v.astype(np.float32)


def compute_cmn(wav_path: str, window_s: float = 1.5,
                hop_s: float = 0.75) -> list[float] | None:
    """Channel-robust 64-dim fingerprint. ADDITIVE - `compute_windowed` is untouched.

    WHY: a recording channel (mic, distance, gain, speaker drive) acts as a filter, which in
    the log-spectral domain is roughly an ADDITIVE CONSTANT, and after the DCT that constant
    lands almost entirely in the MFCC MEANS. The 87-dim fingerprint uses all 20 MFCC means as
    identity features, i.e. it leans on exactly the numbers the channel corrupts. Cepstral mean
    normalization is the classical fix.

    The useful realisation is that CMN here is mostly SUBTRACTION, not new maths:

      * `mc.std(0)` - unchanged by subtracting a per-recording constant. KEPT.
      * `np.diff(mc)` - a constant cancels in a difference. KEPT (means and stds).
      * `mc.mean(0)` - this IS the channel term. DROPPED (20 dims).
      * voiced fraction - thresholded at -32 dB, so it moves directly with level. DROPPED.
      * spectral centroid - computed from log-mel, which shifts additively with level, and the
        weights can go negative so the "centroid" is not well defined anyway. DROPPED (2 dims).
      * F0 stats - pitch is a property of the source, not the channel. KEPT.

    So 87 → 64 by removing the channel-sensitive terms rather than transforming them.

    ⚠️ UNVALIDATED. Round-2 J is currently ambiguous - J1 survived -6.7 dB while J2 broke at
    -3.9 dB - so the hypothesis is that spectral SHAPE (a speaker driven at 50% changes its
    frequency response) matters more than level. This variant should be robust to both.
    Must beat the 87-dim fingerprint on BOTH discrimination and level robustness before it is
    considered, per the A/B agreed with product workstream. Do not make it the default on theory alone.
    """
    y = load_audio(wav_path)
    if y is None:
        return None
    seg, hop = int(window_s * SR), int(hop_s * SR)
    if len(y) < seg:
        v = _fingerprint_cmn_array(y)
        return None if v is None else [float(x) for x in v]
    vs = [_fingerprint_cmn_array(y[s:s + seg]) for s in range(0, len(y) - seg + 1, hop)]
    vs = [v for v in vs if v is not None]
    if not vs:
        return None
    return [float(x) for x in np.mean(vs, axis=0)]


def build_context(started_at: str, prev_started_at: str | None = None,
                  subject_age_days: int | None = None) -> dict:
    """Context per docs/CONTRACTS.md.

    hour_local is the single strongest non-acoustic feature available: infant crying has a
    documented circadian component with an evening peak around 7-8pm (docs/RESEARCH.md §1).
    """
    hour = None
    gap = None
    try:
        dt = datetime.fromisoformat(started_at)
        hour = dt.hour
        if prev_started_at:
            prev = datetime.fromisoformat(prev_started_at)
            if prev.tzinfo != dt.tzinfo and (prev.tzinfo is None or dt.tzinfo is None):
                prev = prev.replace(tzinfo=dt.tzinfo)  # best effort, never raise
            gap = (dt - prev).total_seconds() / 60.0
    except (ValueError, TypeError):
        pass
    return {
        "hour_local": hour,
        "minutes_since_prev_episode": gap,
        "subject_age_days": subject_age_days,
    }
