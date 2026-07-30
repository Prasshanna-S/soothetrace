"""Does the A/B separation survive CHANNEL PERTURBATION? Runs entirely offline.

WHY THIS EXISTS

The remaining leakage worry cannot be settled by argument: Person A's takes are direct
(voice -> phone -> WhatsApp) while Person B's went through a Mac speaker and a room. A real
matched capture is the right fix, but it needs someone to press play.

This asks a different question that needs nobody:

    If the separation is caused by Person A's specific channel signature, then perturbing
    A's channel should DESTROY it. If separation survives many different perturbations of A,
    the classifier is not leaning on A's channel.

Each perturbation simulates a plausible alternative recording path - speaker colouration,
room reflections, band limiting, mild gain drift. If LOO and the blind queries hold across
all of them, the result is channel-robust. If a mild EQ tilt flips the answer, it was never
about the voice.

This is weaker than a matched capture and does NOT replace it. It is a falsification attempt
that can run right now.

Usage: python tools/channel_robustness.py
"""
from __future__ import annotations

import itertools
import os
import subprocess
import sys
import tempfile

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

import config      # noqa: E402
import encoders    # noqa: E402
import store       # noqa: E402

SRC = os.path.join(config.AUDIO_DIR, "replay_master")   # level-normalized sources
A = [f"norm-prasshanna-0{i}" for i in (1, 2, 3)]
B = [f"norm-control-0{i}" for i in (1, 2)]
Q = [f"norm-blind-query-0{i}" for i in (1, 2)]

# Each entry is a plausible ALTERNATIVE channel, expressed as an ffmpeg filter chain.
PERTURBATIONS = {
    "none":            None,
    "speaker-ish":     "highpass=f=120,lowpass=f=7000,equalizer=f=3000:t=q:w=1.2:g=3",
    "small-room":      "aecho=0.8:0.7:22:0.25",
    "bigger-room":     "aecho=0.8:0.6:45:0.35,aecho=0.7:0.5:70:0.2",
    "band-limited":    "highpass=f=200,lowpass=f=4000",
    "bright-tilt":     "equalizer=f=6000:t=q:w=1.5:g=6,equalizer=f=250:t=q:w=1.5:g=-4",
    "dark-tilt":       "equalizer=f=6000:t=q:w=1.5:g=-6,equalizer=f=250:t=q:w=1.5:g=4",
    "quiet-then-norm": "volume=-8dB",
    "phone-speaker":   "highpass=f=300,lowpass=f=6000,aecho=0.9:0.6:18:0.18,"
                       "equalizer=f=1500:t=q:w=2:g=4",
}


def apply_filter(src: str, dst: str, filt: str | None) -> bool:
    cmd = ["ffmpeg", "-v", "error", "-y", "-i", src]
    if filt:
        cmd += ["-af", filt]
    cmd += ["-ac", "1", "-ar", str(config.SAMPLE_RATE), "-c:a", "pcm_s16le", dst]
    try:
        return subprocess.run(cmd, capture_output=True).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def evaluate(enc, vec) -> tuple[int, int, float, list]:
    """LOO over the 5 references + both blind queries."""
    ok = n = 0
    worst = 9.9
    for truth, own, other in (("A", A, B), ("B", B, A)):
        for held in own:
            e_own = [vec[s] for s in own if s != held]
            e_oth = [vec[s] for s in other]
            so = float(np.mean([v @ vec[held] for v in e_own]))
            sx = float(np.mean([v @ vec[held] for v in e_oth]))
            n += 1
            ok += so > sx
            worst = min(worst, abs(so - sx))
    blind = []
    for q in Q:
        sa = float(np.mean([vec[s] @ vec[q] for s in A]))
        sb = float(np.mean([vec[s] @ vec[q] for s in B]))
        blind.append(("A" if sa > sb else "B", sa - sb))
    return ok, n, worst, blind


def main() -> int:
    base = store.get_baseline(config.POPULATION_KEY)
    if not base:
        print("run tools/build_baseline.py first", file=sys.stderr)
        return 1
    BASE = (np.asarray(base["mu"]), np.asarray(base["sd"]))

    for s in A + B + Q:
        if not os.path.exists(os.path.join(SRC, f"{s}.wav")):
            print(f"missing {s}.wav - run tools/prep_replay.py first", file=sys.stderr)
            return 1

    print("=" * 76)
    print(" CHANNEL-ROBUSTNESS FALSIFICATION TEST")
    print("=" * 76)
    print("\n Perturbing ONLY Person A's recordings. If the A/B separation comes from A's")
    print(" channel signature, these should break it. Person B and the blind queries are")
    print(" left untouched, so any collapse is attributable to A's channel.\n")
    print(" NOTE: this is weaker than a real matched capture and does not replace it.\n")

    encs = [encoders.MFCC87, encoders.ECAPA_CRY]
    results = {e: [] for e in encs}

    with tempfile.TemporaryDirectory() as tmp:
        for pname, filt in PERTURBATIONS.items():
            # perturb A only; B and queries stay as they are
            paths = {}
            for s in A:
                dst = os.path.join(tmp, f"{pname}-{s}.wav")
                if not apply_filter(os.path.join(SRC, f"{s}.wav"), dst, filt):
                    print(f"  {pname}: ffmpeg failed", file=sys.stderr)
                    paths = None
                    break
                paths[s] = dst
            if paths is None:
                continue
            for s in B + Q:
                paths[s] = os.path.join(SRC, f"{s}.wav")

            for enc in encs:
                raw = {}
                bad = False
                for s, p in paths.items():
                    v = encoders.encode(enc, p)
                    if v is None:
                        bad = True
                        break
                    raw[s] = v
                if bad:
                    print(f"  {pname} / {enc}: unusable audio after filter")
                    continue
                ks = list(raw)
                P = encoders.prepare(enc, [raw[k] for k in ks],
                                     BASE if encoders.needs_baseline(enc) else None)
                vec = dict(zip(ks, P))
                ok, n, worst, blind = evaluate(enc, vec)
                results[enc].append((pname, ok, n, worst, blind))

    for enc in encs:
        print(f"\n {enc}")
        print(f"   {'perturbation':18} {'LOO':>6} {'blind':>7} {'min-margin':>11}  blind margins")
        for pname, ok, n, worst, blind in results[enc]:
            nb = sum(1 for b in blind if b[0] == "A")
            flag = "" if (ok == n and nb == len(blind)) else "   <-- DEGRADED"
            print(f"   {pname:18} {ok}/{n:<4} {nb}/{len(blind):<5} {worst:+11.4f}  "
                  + " ".join(f"{m:+.4f}" for _, m in blind) + flag)

    print("\n" + "=" * 76)
    print(" VERDICT")
    print("=" * 76)
    for enc in encs:
        rows = results[enc]
        if not rows:
            continue
        perfect = sum(1 for _, ok, n, _, bl in rows
                      if ok == n and all(b[0] == "A" for b in bl))
        worst_margin = min(w for _, _, _, w, _ in rows)
        print(f"\n  {enc}: {perfect}/{len(rows)} perturbations fully correct, "
              f"worst LOO margin across all {worst_margin:+.4f}")
        if perfect == len(rows):
            print("    ✅ Separation survives every simulated alternative channel for A.")
            print("       The result is not explained by A's channel signature.")
        elif perfect >= len(rows) - 2:
            print("    ⚠️  Mostly robust; a couple of channels degrade it. Note which.")
        else:
            print("    🔴 Fragile to channel. The separation is substantially channel, not")
            print("       voice. Do NOT build the visitor flow on this.")
    print("\n  Still required for a clean answer: the matched replay capture "
          "(REPLAY-MASTER.wav).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
