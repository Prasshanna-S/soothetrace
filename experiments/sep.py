"""❌ DEAD END - KEPT AS EVIDENCE. DO NOT USE IN src/.

Attempt: split a mixed caregiver+infant recording into two channels by per-frame F0,
on the theory that infant cry (~350-600 Hz) and adult speech (~85-255 Hz) separate cleanly.

MEASURED RESULT: it makes both paths worse.

  - Separated cry channel vs the clean original cry: cosine +0.031
    -> 57.4th percentile among 430 IMPOSTOR cries. Literally no better than a stranger.
    The untouched mixture scores +0.474 (99.3rd percentile).
  - Separated speech channel transcription LOST HALF THE SENTENCE.
    The untouched mixture transcribed verbatim.

WHY IT FAILS: the pitch ranges genuinely overlap. Measured on real audio - 
  cry:       F0 median 432.4 Hz, p10 240.6, p90 761.9
  caregiver: F0 median 188.2 Hz, p10 166.7, p90 280.7
Cry p10 (240 Hz) sits BELOW caregiver p90 (281 Hz). No threshold separates them.
Run on a PURE cry with no speech at all, this still mislabels 19.6% of frames as speech,
and gating those away is what collapses the fingerprint.

CONCLUSION: feed the raw mixture to both paths. Speech ASR ignores the cry by itself; the
MFCC fingerprint survives speech laid over it. Full detail: docs/FINDINGS.md §3.
"""
import numpy as np, subprocess, sys
SR = 16000
WIN, HOP = 1024, 160          # 64 ms window, 10 ms hop

def load(path, sr=SR):
    p = subprocess.run(["ffmpeg","-v","quiet","-i",path,"-f","f32le","-ac","1","-ar",str(sr),"-"],
                       capture_output=True)
    return np.frombuffer(p.stdout, dtype=np.float32).copy()

def write(path, y, sr=SR):
    pcm = np.clip(y, -1, 1)
    subprocess.run(["ffmpeg","-v","quiet","-y","-f","f32le","-ac","1","-ar",str(sr),
                    "-i","pipe:0","-c:a","pcm_s16le",path], input=pcm.astype(np.float32).tobytes())

def frame_f0(w, sr=SR, fmin=70, fmax=900):
    """Autocorrelation F0 for one frame. Returns (f0, clarity)."""
    w = (w - w.mean()) * np.hanning(len(w))
    if np.sqrt((w**2).mean()) < 2e-3:
        return 0.0, 0.0
    ac = np.correlate(w, w, "full")[len(w)-1:]
    if ac[0] <= 0: return 0.0, 0.0
    lo, hi = int(sr/fmax), min(int(sr/fmin), len(ac)-1)
    if hi <= lo: return 0.0, 0.0
    seg = ac[lo:hi]
    pk = int(np.argmax(seg)) + lo
    return sr/pk, float(ac[pk]/ac[0])

def analyse(y):
    """Per-frame label: 2=cry(high F0), 1=speech(low F0), 0=silence/unvoiced."""
    n = 1 + max(0, (len(y)-WIN)//HOP)
    lab = np.zeros(n, np.int8); f0s = np.zeros(n)
    for i in range(n):
        f0, clar = frame_f0(y[i*HOP:i*HOP+WIN])
        f0s[i] = f0
        if clar < 0.30: continue
        if f0 >= 300:   lab[i] = 2
        elif 70 <= f0 < 280: lab[i] = 1
    return lab, f0s

def smooth(lab, k=9):
    """Majority filter - cries and words last far longer than one 10 ms frame."""
    out = lab.copy()
    for i in range(len(lab)):
        w = lab[max(0,i-k//2):i+k//2+1]
        w = w[w > 0]
        if len(w): out[i] = np.bincount(w).argmax()
    return out

def gate(y, lab, want):
    """Reconstruct one channel by keeping only frames of the wanted class."""
    m = np.zeros(len(y))
    for i, L in enumerate(lab):
        if L == want: m[i*HOP:i*HOP+WIN] = 1.0
    k = np.hanning(161); k /= k.sum()
    m = np.convolve(m, k, "same")
    return y * np.clip(m, 0, 1)

def separate(path, out_cry=None, out_speech=None):
    y = load(path)
    lab = smooth(analyse(y)[0])
    cry, sp = gate(y, lab, 2), gate(y, lab, 1)
    if out_cry: write(out_cry, cry)
    if out_speech: write(out_speech, sp)
    return {"frames": len(lab), "cry_%": (lab==2).sum()/len(lab),
            "speech_%": (lab==1).sum()/len(lab), "sil_%": (lab==0).sum()/len(lab)}

if __name__ == "__main__":
    print(separate(sys.argv[1], sys.argv[2], sys.argv[3]))
