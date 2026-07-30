"""Acoustic fingerprinting for infant cries - numpy/scipy only.

REFERENCE IMPLEMENTATION. `src/fingerprint.py` must reproduce `fingerprint()` exactly;
all measured results in docs/FINDINGS.md come from this file.

Question this was built to answer: within ONE baby, do separate crying episodes separate
acoustically, or do all of that baby's cries collapse into one cluster?
Answer: they separate. AUC 0.70. See docs/FINDINGS.md §1.

No librosa on purpose - its numba/llvmlite dependency will not build on Python 3.12/macOS ARM.
"""
import numpy as np, soundfile as sf, subprocess, io, os, glob, re
from scipy.fftpack import dct

SR = 16000

def load(path, sr=SR):
    """Decode anything ffmpeg understands to mono float32 at sr."""
    p = subprocess.run(
        ["ffmpeg", "-v", "quiet", "-i", path, "-f", "f32le", "-ac", "1", "-ar", str(sr), "-"],
        capture_output=True)
    if p.returncode != 0 or not p.stdout:
        return None
    return np.frombuffer(p.stdout, dtype=np.float32).copy()

def mel_fb(n_filt=40, n_fft=512, sr=SR):
    lo, hi = 0.0, 2595 * np.log10(1 + (sr / 2) / 700)
    pts = np.linspace(lo, hi, n_filt + 2)
    hz = 700 * (10 ** (pts / 2595) - 1)
    bins = np.floor((n_fft + 1) * hz / sr).astype(int)
    fb = np.zeros((n_filt, n_fft // 2 + 1))
    for m in range(1, n_filt + 1):
        l, c, r = bins[m - 1], bins[m], bins[m + 1]
        if c == l: c = l + 1
        if r == c: r = c + 1
        if r >= fb.shape[1]: r = fb.shape[1] - 1
        if c >= r: continue
        fb[m - 1, l:c] = (np.arange(l, c) - l) / max(c - l, 1)
        fb[m - 1, c:r] = (r - np.arange(c, r)) / max(r - c, 1)
    return fb

FB = mel_fb()

def frames(y, n_fft=512, hop=160):
    if len(y) < n_fft: return np.zeros((0, n_fft))
    idx = np.arange(0, len(y) - n_fft, hop)
    f = np.stack([y[i:i + n_fft] for i in idx])
    return f * np.hamming(n_fft)

def logmel(y):
    f = frames(y)
    if len(f) == 0: return np.zeros((0, FB.shape[0]))
    spec = np.abs(np.fft.rfft(f, axis=1)) ** 2
    return np.log(spec @ FB.T + 1e-10)

def mfcc(y, n=20):
    lm = logmel(y)
    if len(lm) == 0: return np.zeros((0, n))
    return dct(lm, type=2, axis=1, norm="ortho")[:, :n]

def f0_track(y, sr=SR, fmin=150, fmax=900):
    """Autocorrelation F0 - infant cries sit high, measured median ~432 Hz."""
    win, hop = 1024, 256
    out = []
    for i in range(0, max(len(y) - win, 0), hop):
        w = y[i:i + win] * np.hanning(win)
        if np.sqrt((w ** 2).mean()) < 1e-3:
            continue
        w = w - w.mean()
        ac = np.correlate(w, w, "full")[win - 1:]
        lo, hi = int(sr / fmax), int(sr / fmin)
        if hi >= len(ac): continue
        seg = ac[lo:hi]
        if len(seg) == 0 or ac[0] <= 0: continue
        pk = np.argmax(seg) + lo
        if ac[pk] / ac[0] > 0.3:
            out.append(sr / pk)
    return np.array(out)

def voiced_mask(y, thresh_db=-32):
    """Keep only energetic (crying) frames; drop silence/room tone."""
    win, hop = 512, 160
    keep = np.zeros(len(y), bool)
    for i in range(0, max(len(y) - win, 0), hop):
        rms = np.sqrt((y[i:i + win] ** 2).mean() + 1e-12)
        if 20 * np.log10(rms + 1e-12) > thresh_db:
            keep[i:i + win] = True
    return keep

def fingerprint(y):
    """87-dim UN-normalized acoustic fingerprint. None if <0.3 s of voiced audio.

    Layout: 20 MFCC means | 20 MFCC SDs | 20 delta means | 20 delta SDs
            | F0 mean/SD/p10/p90 | centroid mean/SD | voiced fraction

    ⚠️ CALLERS MUST z-score against a stored baseline before cosine. On raw vectors a
    DIFFERENT baby scores +0.9999 while a file matches itself at +0.9915 - everything
    matches everything. See docs/FINDINGS.md §5.
    """
    m = voiced_mask(y)
    if m.sum() < SR * 0.3:
        return None
    yv = y[m]
    mc = mfcc(yv)
    if len(mc) < 5: return None
    d = np.diff(mc, axis=0)
    f0 = f0_track(yv)
    f0s = ([f0.mean(), f0.std(), np.percentile(f0, 10), np.percentile(f0, 90)]
           if len(f0) > 3 else [0, 0, 0, 0])
    lm = logmel(yv)
    cent = (lm * np.arange(lm.shape[1])).sum(1) / (lm.sum(1) + 1e-9) if len(lm) else np.zeros(1)
    return np.concatenate([mc.mean(0), mc.std(0), d.mean(0), d.std(0),
                           f0s, [cent.mean(), cent.std()],
                           [float(m.mean())]])

META = re.compile(r"^(?P<uuid>[0-9A-Fa-f-]{36})-(?P<ts>\d+)-")

def parse(path):
    """donateacry filename → metadata. UUID = device ≈ one infant; ts = one episode."""
    b = os.path.basename(path)
    m = META.match(b)
    if not m: return None
    return {"path": path, "uuid": m["uuid"].lower(), "ts": m["ts"],
            "label": os.path.basename(os.path.dirname(path)), "file": b}
