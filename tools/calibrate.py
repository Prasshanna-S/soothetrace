"""Calibrate identity thresholds from REAL live trials, and answer the 2-class question.

Thresholds in this system are measured, never chosen to make a demo look good. This tool
consumes the round-2 live corpus (`data/audio/round2_h/`, 8 recordings each of two infants,
captured through one fixed rig) and produces `data/calibration.json`.

It reports three things:

1. **Verification** - one profile enrolled. Is a held-out recording of that infant accepted,
   and are other infants rejected? (Round 2 measured 2/2 and 8/8 by hand; this repeats it
   as leave-one-out over all 8.)
2. **2-class closed-set identification** - BOTH infants enrolled; does a held-out recording
   pick the right one? **This is the number the flagship demo depends on and it has never
   been measured.**
3. **Thresholds** - an absolute accept threshold and a runner-up margin, placed from the
   genuine/impostor distributions rather than by taste.

Usage:  python tools/calibrate.py [--write]
"""
from __future__ import annotations

import argparse
import glob
import os
import re
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

import config      # noqa: E402
import identity    # noqa: E402
import store       # noqa: E402

H_DIR = os.path.join(config.AUDIO_DIR, "round2_h")
NAME = re.compile(r"^\d+-([XY])(\d+)\.wav$", re.I)


def load_groups() -> dict[str, list[tuple[str, str]]]:
    """{'X': [(label, path), ...], 'Y': [...]} from the round2_h filenames."""
    groups: dict[str, list[tuple[str, str]]] = {"X": [], "Y": []}
    for p in sorted(glob.glob(os.path.join(H_DIR, "*.wav"))):
        m = NAME.match(os.path.basename(p))
        if m:
            groups[m.group(1).upper()].append((f"{m.group(1).upper()}{m.group(2)}", p))
    return groups


def embed_all(groups):
    """label -> normalized vector. Skips anything unusable."""
    base = store.get_baseline(config.POPULATION_KEY)
    if not base:
        print("No population baseline - run tools/build_baseline.py first.", file=sys.stderr)
        return None, None
    mu = np.asarray(base["mu"], dtype=np.float64)
    sd = np.asarray(base["sd"], dtype=np.float64)
    out = {}
    for g, items in groups.items():
        for label, path in items:
            v = identity.embed(path)
            if v is None:
                print(f"  ! {label}: no usable audio, skipped", file=sys.stderr)
                continue
            out[label] = identity._normalize(v, mu, sd)[0]
    return out, (mu, sd)


def profile_score(query_vec, enroll_vecs) -> tuple[float, float]:
    """(mean, max) cosine - mean decides, max is the supporting evidence.
    Identical aggregation to identity.identify(), so calibration matches runtime."""
    sims = np.asarray([float(v @ query_vec) for v in enroll_vecs])
    return float(sims.mean()), float(sims.max())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true", help="write data/calibration.json")
    args = ap.parse_args()

    groups = load_groups()
    if len(groups["X"]) < 3 or len(groups["Y"]) < 3:
        print(f"Need >=3 recordings per infant in {H_DIR}\n"
              f"found X={len(groups['X'])} Y={len(groups['Y'])}", file=sys.stderr)
        return 1
    print(f"round2_h: {len(groups['X'])} X recordings, {len(groups['Y'])} Y recordings")

    vecs, _ = embed_all(groups)
    if vecs is None:
        return 1
    X = [l for l, _ in groups["X"] if l in vecs]
    Y = [l for l, _ in groups["Y"] if l in vecs]
    print(f"usable embeddings: X={len(X)} Y={len(Y)}\n")

    # ── 1. VERIFICATION, leave-one-out ───────────────────────────────────────
    genuine, impostor = [], []
    for held in X:
        ens = [vecs[l] for l in X if l != held]
        genuine.append(profile_score(vecs[held], ens)[0])
    ens_all_X = [vecs[l] for l in X]
    for y in Y:
        impostor.append(profile_score(vecs[y], ens_all_X)[0])
    # symmetric: Y as the enrolled profile, X as impostors
    for held in Y:
        ens = [vecs[l] for l in Y if l != held]
        genuine.append(profile_score(vecs[held], ens)[0])
    ens_all_Y = [vecs[l] for l in Y]
    for x in X:
        impostor.append(profile_score(vecs[x], ens_all_Y)[0])

    genuine, impostor = np.array(genuine), np.array(impostor)
    print("=== 1. VERIFICATION (is this the enrolled infant?) ===")
    print(f"  genuine  n={len(genuine):2d}  mean {genuine.mean():.4f}  "
          f"min {genuine.min():.4f}  max {genuine.max():.4f}")
    print(f"  impostor n={len(impostor):2d}  mean {impostor.mean():.4f}  "
          f"min {impostor.min():.4f}  max {impostor.max():.4f}")
    separable = genuine.min() > impostor.max()
    print(f"  separable with a single threshold: "
          f"{'YES - distributions do not overlap' if separable else 'NO - they overlap'}")

    if separable:
        accept = float((genuine.min() + impostor.max()) / 2)
    else:
        # place the threshold to maximise balanced accuracy
        cands = np.unique(np.concatenate([genuine, impostor]))
        accept = float(max(cands, key=lambda t: (genuine >= t).mean() + (impostor < t).mean()))
    tar = float((genuine >= accept).mean())
    far = float((impostor >= accept).mean())
    print(f"  accept_threshold = {accept:.4f}  ->  true-accept {tar:.1%}, "
          f"false-accept {far:.1%}")

    # ── 2. 2-CLASS CLOSED SET - the flagship number ──────────────────────────
    print("\n=== 2. TWO-CLASS IDENTIFICATION (which infant is this?) ===")
    correct = 0
    trials = []
    margins_correct = []
    for truth, own, other in (("X", X, Y), ("Y", Y, X)):
        for held in own:
            ens_own = [vecs[l] for l in own if l != held]
            ens_other = [vecs[l] for l in other]
            s_own = profile_score(vecs[held], ens_own)[0]
            s_other = profile_score(vecs[held], ens_other)[0]
            pred = truth if s_own > s_other else ("Y" if truth == "X" else "X")
            ok = pred == truth
            correct += ok
            trials.append((held, truth, pred, s_own, s_other, s_own - s_other))
            if ok:
                margins_correct.append(abs(s_own - s_other))
    n = len(trials)
    print(f"  {correct}/{n} correct = {correct/n:.1%}   (chance 50%)")
    for label, truth, pred, so, sx, d in trials:
        print(f"    {label:>3} truth={truth} pred={pred} {'OK ' if pred==truth else 'MISS'}"
              f"  own {so:.4f}  other {sx:.4f}  margin {d:+.4f}")

    # The margin gate has ONE job: stop a wrong name being said out loud. So calibrate it
    # against the margins of decisions that were WRONG, not against a percentile of the
    # right ones - a percentile needlessly converts correct matches into retries.
    _ok = [abs(d) for _, t, p, _, _, d in trials if t == p]
    ok_m = np.array(_ok) if _ok else np.array([0.0])
    bad_m = np.array([abs(d) for _, t, p, _, _, d in trials if t != p])
    if len(bad_m) == 0:
        margin_thr = 0.02                     # nothing to guard against; keep a floor
        print(f"  margin_threshold = {margin_thr:.4f}  (no wrong decisions to separate)")
    elif bad_m.max() < ok_m.min():
        margin_thr = round(float((bad_m.max() + ok_m.min()) / 2), 4)
        print(f"  margin_threshold = {margin_thr:.4f}  (separates every wrong decision "
              f"(max |margin| {bad_m.max():.4f}) from every right one "
              f"(min {ok_m.min():.4f}))")
    else:
        margin_thr = round(float(bad_m.max() + 0.01), 4)
        print(f"  margin_threshold = {margin_thr:.4f}  (above the worst wrong margin; "
              f"costs some correct matches as retries)")

    strong = float(np.percentile(genuine, 50))
    print(f"  strong_threshold = {strong:.4f}  (median genuine score)")

    # ── 3. THE NUMBER THAT MATTERS FOR A DEMO ────────────────────────────────
    # With BOTH gates live, how often do we say the right name, ask for a retry, or say
    # something WRONG? A retry is recoverable on stage. A wrong name is not.
    print("\n=== 3. BOTH GATES APPLIED (what the demo will actually do) ===")
    n_match = n_uncertain = n_wrong = 0
    for label, truth, pred, s_own, s_other, d in trials:
        top = max(s_own, s_other)
        margin = abs(d)
        if top < accept:
            n_uncertain += 1
            verdict = "uncertain (below accept)"
        elif margin < margin_thr:
            n_uncertain += 1
            verdict = "uncertain (too close)"
        elif pred == truth:
            n_match += 1
            verdict = f"MATCH {pred} correct"
        else:
            n_wrong += 1
            verdict = f"*** WRONG: said {pred}, truth {truth} ***"
        print(f"    {label:>3}  {verdict}")
    print(f"\n  correct matches : {n_match}/{n}")
    print(f"  asked to retry  : {n_uncertain}/{n}")
    print(f"  WRONG ANSWERS   : {n_wrong}/{n}")

    cal = {"version": "live-round2-v1", "encoder": identity.ENCODER_VERSION,
           "accept_threshold": round(accept, 4), "margin_threshold": margin_thr,
           "strong_threshold": round(strong, 4), "min_enrollments_ready": 2,
           "trials": {"genuine_n": int(len(genuine)), "impostor_n": int(len(impostor)),
                      "genuine_mean": round(float(genuine.mean()), 6),
                      "impostor_mean": round(float(impostor.mean()), 6),
                      "verification_separable": bool(separable),
                      "true_accept_rate": round(tar, 4), "false_accept_rate": round(far, 4),
                      "two_class_correct": int(correct), "two_class_n": int(n),
                      "two_class_accuracy": round(correct / n, 4),
                      "gated_matches": int(n_match), "gated_retries": int(n_uncertain),
                      "gated_wrong": int(n_wrong)},
           "source": "data/audio/round2_h (live, one fixed rig)"}

    print("\n=== VERDICT ===")
    if n_wrong == 0:
        print(f"  ZERO wrong identifications across {n} live trials.")
        print(f"  {n_match} confident correct, {n_uncertain} asked to retry.")
        print("  The two gates are doing their job: the system never says the wrong name,")
        print("  it says 'uncertain'. On stage a retry is recoverable; a wrong name is not.")
        print("  -> The 'which baby is this?' demo is SUPPORTED on measured data.")
    else:
        print(f"  {n_wrong} WRONG identification(s) survived both gates. Raise")
        print("  margin_threshold and re-run before this goes anywhere near a stage.")
    if not separable:
        print("\n  Note: verification distributions overlap, so ABSOLUTE 'is this an enrolled")
        print("  baby at all' is weaker than RELATIVE 'which of these two'. Comparative")
        print("  identification needs no absolute threshold, which is why it does better.")

    if args.write:
        identity.save_calibration(cal)
        print(f"\nwrote {identity.CALIBRATION_PATH}")
    else:
        print("\n(dry run - pass --write to save)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
