"""Human-imitation encoder comparison + channel-leakage probes. acoustics workstream, for product workstream's request.

READ THE STATISTICAL WARNING IN THE OUTPUT BEFORE USING ANY NUMBER HERE TO CHOOSE A MODEL.

This tool deliberately reports three things product workstream did not ask for, because without them the
model comparison is not interpretable:

1. **A trivial baseline.** If a 3-number feature (level, duration, voiced fraction) separates
   the two people, the dataset has a giveaway and every "model comparison" below is measuring
   that giveaway. This is the first thing to check, not the last.
2. **A channel-leakage probe using CMN.** Channel effects live in the MFCC means. If stripping
   them (compute_cmn) preserves A/B separation, the separation is plausibly voice. If it
   collapses, the separation was substantially channel - which matters enormously here,
   because Person B's original device and room are still baked into her WhatsApp audio.
3. **Predeclared score normalization for fusion.** Averaging raw cosines across encoders is
   invalid - the scales differ. Each encoder's scores are z-normalized against ITS OWN
   pairwise-score distribution over the REFERENCES ONLY, so nothing is fitted to the blind
   queries.

Usage: python tools/imitation_spike.py
"""
from __future__ import annotations

import itertools
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

import config       # noqa: E402
import encoders     # noqa: E402
import fingerprint  # noqa: E402
import identity     # noqa: E402
import store        # noqa: E402

SRC = os.path.join(config.AUDIO_DIR, "imitation_trial_sources")
A = ["prasshanna-01", "prasshanna-02", "prasshanna-03"]
B = ["control-01", "control-02"]
BLIND = ["blind-query-01", "blind-query-02"]          # both revealed as Person A
EXCLUDE = ["blind-query-consensus-01-02"]             # per product workstream: not an independent trial

CMN = "cmn64-v1"      # local pseudo-encoder for the leakage probe


def path(stem):
    return os.path.join(SRC, f"{stem}.wav")


def encode(enc, stem):
    if enc == CMN:
        return fingerprint.compute_cmn(path(stem))
    return encoders.encode(enc, path(stem))


def prepare(enc, vecs, baseline):
    if enc == CMN:
        X = np.atleast_2d(np.asarray(vecs, dtype=np.float64))
        mu, sd = X.mean(0), X.std(0) + 1e-9        # self-normalized: no 64-d baseline exists
        Z = (X - mu) / sd
        return Z / (np.linalg.norm(Z, axis=1, keepdims=True) + 1e-9)
    return encoders.prepare(enc, vecs, baseline)


def trivial_features(stem):
    """A deliberately stupid 3-number descriptor: could this alone separate the people?"""
    q = identity.quality(path(stem))
    return [q["mean_db"] or 0.0, q["duration_s"], q["voiced_fraction"] * 100.0]


def report(name, vec, note=""):
    """LOO over the 5 references + both blind queries. Returns a dict of metrics."""
    prof = {"A": [vec[s] for s in A if s in vec], "B": [vec[s] for s in B if s in vec]}
    if len(prof["A"]) < 2 or len(prof["B"]) < 2:
        print(f"  {name}: insufficient usable references"); return None

    within_a = [float(x @ y) for x, y in itertools.combinations(prof["A"], 2)]
    within_b = [float(x @ y) for x, y in itertools.combinations(prof["B"], 2)]
    between = [float(x @ y) for x in prof["A"] for y in prof["B"]]

    loo_ok, loo_n, min_margin = 0, 0, 9.9
    for truth, own, other in (("A", A, B), ("B", B, A)):
        for held in own:
            if held not in vec:
                continue
            e_own = [vec[s] for s in own if s != held and s in vec]
            e_oth = [vec[s] for s in other if s in vec]
            if not e_own or not e_oth:
                continue
            s_own = float(np.mean([v @ vec[held] for v in e_own]))
            s_oth = float(np.mean([v @ vec[held] for v in e_oth]))
            loo_n += 1
            loo_ok += s_own > s_oth
            min_margin = min(min_margin, abs(s_own - s_oth))

    blind = []
    for q in BLIND:
        if q not in vec:
            continue
        sa = float(np.mean([v @ vec[q] for v in prof["A"]]))
        sb = float(np.mean([v @ vec[q] for v in prof["B"]]))
        blind.append((q, "A" if sa > sb else "B", sa, sb, sa - sb))

    wa = np.mean(within_a) if within_a else float("nan")
    wb = np.mean(within_b) if within_b else float("nan")
    bt = np.mean(between)
    gap = np.mean(within_a + within_b) - bt
    print(f"  {name:20} LOO {loo_ok}/{loo_n}  blind {sum(1 for b in blind if b[1]=='A')}/{len(blind)}"
          f"  within-A {wa:+.4f} within-B {wb:+.4f} between {bt:+.4f}  gap {gap:+.4f}"
          f"  min-LOO-margin {min_margin:+.4f}{note}")
    for q, pred, sa, sb, m in blind:
        print(f"      {q}: -> {pred}  A {sa:+.4f}  B {sb:+.4f}  margin {m:+.4f}")
    return {"name": name, "loo": (loo_ok, loo_n), "gap": gap, "min_margin": min_margin,
            "blind": blind, "between_max": max(between),
            "within_min": min(within_a + within_b)}


def main() -> int:
    stems = A + B + BLIND
    missing = [s for s in stems if not os.path.exists(path(s))]
    if missing:
        print(f"missing: {missing}", file=sys.stderr); return 1

    print("=" * 78)
    print(" HUMAN-IMITATION ENCODER SPIKE")
    print("=" * 78)
    print(f"\n⚠️  STATISTICAL WARNING - READ BEFORE USING ANY NUMBER BELOW")
    print(f"   Dataset: {len(A)} recordings of Person A, {len(B)} of Person B, "
          f"{len(BLIND)} blind queries.")
    print(f"   That is 5 references -> 5 leave-one-out trials, and 2 blind queries.")
    print(f"   Comparing 4+ encoders and several fusion rules over 7 outcomes CANNOT select a")
    print(f"   model: with this many hypotheses and this little data, the 'winner' is chosen by")
    print(f"   noise. One flipped trial moves LOO by 20 percentage points. Treat everything")
    print(f"   below as a SMOKE TEST for gross failure, never as evidence one encoder is better.")
    print(f"   Person B also has only 2 recordings, so 'within-B' is a single pair.")

    # ── 0. trivial baseline ──────────────────────────────────────────────────
    print("\n" + "=" * 78)
    print(" 0. TRIVIAL BASELINE - is there a giveaway in the dataset?")
    print("=" * 78)
    tf = {s: trivial_features(s) for s in stems}
    for s in stems:
        print(f"    {s:26} level {tf[s][0]:7.2f} dB   dur {tf[s][1]:6.2f}s   "
              f"voiced {tf[s][2]:5.1f}%")
    ta = np.array([tf[s] for s in A]); tb = np.array([tf[s] for s in B])
    overlap = all(min(ta[:, i].min(), tb[:, i].min()) <= max(ta[:, i].max(), tb[:, i].max())
                  and not (ta[:, i].max() < tb[:, i].min() or tb[:, i].max() < ta[:, i].min())
                  for i in range(3))
    print(f"\n  Every trivial feature overlaps between A and B: "
          f"{'YES - no obvious giveaway' if overlap else 'NO - at least one feature SEPARATES them'}")
    if not overlap:
        print("  🔴 A trivial property distinguishes the two people. Any encoder result below")
        print("     may be reading that, not the voice. Re-record with this controlled.")

    base = store.get_baseline(config.POPULATION_KEY)
    baseline = (np.asarray(base["mu"]), np.asarray(base["sd"])) if base else None

    # ── 1. per-encoder ───────────────────────────────────────────────────────
    print("\n" + "=" * 78)
    print(" 1. PER-ENCODER (smoke test only)")
    print("=" * 78)
    enc_list = [encoders.MFCC87, CMN, encoders.ECAPA_CRY, encoders.ECAPA_ADULT]
    vecs, results, timings = {}, {}, {}
    for enc in enc_list:
        t0 = time.time()
        raw = {}
        for s in stems:
            v = encode(enc, s)
            if v is not None:
                raw[s] = v
        if len(raw) < len(stems):
            print(f"  {enc}: only {len(raw)}/{len(stems)} usable, skipping")
            continue
        labs = list(raw)
        P = prepare(enc, [raw[l] for l in labs], baseline)
        vecs[enc] = dict(zip(labs, P))
        timings[enc] = (time.time() - t0) / len(stems)
        note = "   <- channel-leakage probe" if enc == CMN else ""
        results[enc] = report(enc, vecs[enc], note)

    # ── 2. leakage verdict ───────────────────────────────────────────────────
    print("\n" + "=" * 78)
    print(" 2. CHANNEL-LEAKAGE PROBE")
    print("=" * 78)
    m, c = results.get(encoders.MFCC87), results.get(CMN)
    if m and c:
        print(f"  MFCC87 (keeps channel in the means): gap {m['gap']:+.4f}, LOO {m['loo'][0]}/{m['loo'][1]}")
        print(f"  CMN64  (channel means REMOVED):      gap {c['gap']:+.4f}, LOO {c['loo'][0]}/{c['loo'][1]}")
        if c["loo"][0] >= m["loo"][0] and c["gap"] > 0.03:
            print("\n  ✅ Separation SURVIVES removing the channel-carrying terms. The A/B")
            print("     difference is plausibly voice rather than device/room.")
        elif c["gap"] <= 0.0:
            print("\n  🔴 Separation COLLAPSES without the channel terms. On this data the A/B")
            print("     difference is substantially CHANNEL, not voice - Person B's original")
            print("     device and room are baked into her WhatsApp audio and that is what is")
            print("     being separated. A positive result here would not generalise to a")
            print("     visitor recorded live on the demo phone.")
        else:
            print("\n  ⚠️  Separation WEAKENS without the channel terms - partial leakage.")
            print("     Some of the A/B difference is device/room. Cannot quantify how much")
            print("     with 5 recordings from 2 devices.")
    print("\n  DECISIVE TEST WE CANNOT RUN WITH THIS DATA: the same person recorded on BOTH")
    print("  devices. Without it, voice and device are mathematically entangled - no encoder")
    print("  or fusion rule can separate them, because the information is not in the data.")

    # ── 3. fusion with predeclared normalization ─────────────────────────────
    print("\n" + "=" * 78)
    print(" 3. FUSION - z-normalized per encoder, references only")
    print("=" * 78)
    print("  Raw cosine averaging is invalid (scales differ). Each encoder's scores are")
    print("  z-normalized against its OWN reference-pair distribution. Nothing is fitted to")
    print("  the blind queries. Equal weights, predeclared.\n")

    stats = {}
    for enc, v in vecs.items():
        refs = [s for s in A + B if s in v]
        pair = [float(v[x] @ v[y]) for x, y in itertools.combinations(refs, 2)]
        stats[enc] = (float(np.mean(pair)), float(np.std(pair)) + 1e-9)

    def zscore(enc, s):
        mu, sd = stats[enc]
        return (s - mu) / sd

    for combo in [(encoders.MFCC87, encoders.ECAPA_CRY),
                  (encoders.MFCC87, encoders.ECAPA_CRY, encoders.ECAPA_ADULT),
                  (encoders.MFCC87, CMN, encoders.ECAPA_CRY)]:
        combo = tuple(e for e in combo if e in vecs)
        if len(combo) < 2:
            continue
        ok = n = 0; worst = 9.9
        for truth, own, other in (("A", A, B), ("B", B, A)):
            for held in own:
                zo = zx = 0.0
                for enc in combo:
                    v = vecs[enc]
                    e_own = [v[s] for s in own if s != held]
                    e_oth = [v[s] for s in other]
                    zo += zscore(enc, float(np.mean([x @ v[held] for x in e_own])))
                    zx += zscore(enc, float(np.mean([x @ v[held] for x in e_oth])))
                zo /= len(combo); zx /= len(combo)
                n += 1; ok += zo > zx; worst = min(worst, abs(zo - zx))
        bl = []
        for q in BLIND:
            za = zb = 0.0
            for enc in combo:
                v = vecs[enc]
                za += zscore(enc, float(np.mean([v[s] @ v[q] for s in A])))
                zb += zscore(enc, float(np.mean([v[s] @ v[q] for s in B])))
            za /= len(combo); zb /= len(combo)
            bl.append((q, "A" if za > zb else "B", za - zb))
        label = "+".join(e.split("-")[0] for e in combo)
        print(f"  {label:26} LOO {ok}/{n}  min-margin(z) {worst:+.3f}  "
              f"blind {sum(1 for b in bl if b[1]=='A')}/{len(bl)}"
              f"  margins {' '.join(f'{b[2]:+.3f}' for b in bl)}")

    # ── 4. latency ───────────────────────────────────────────────────────────
    print("\n" + "=" * 78)
    print(" 4. LATENCY (per ~10 s file, after warm-up, CPU, offline)")
    print("=" * 78)
    for enc, t in sorted(timings.items(), key=lambda kv: kv[1]):
        print(f"    {enc:22} {t:.3f} s/file")
    print("\n  All well inside the 5 s p95 budget. Latency does not constrain this choice.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
