"""Task 10 - the TWO-PROFILE operating point, calibrated and evaluated at pool size 2.

WHY THIS EXISTS

The 5-fold grouped CV calibrated thresholds inside 36-37 profile pools and evaluated inside
9-10 profile pools. **Margin distributions depend on pool size** - with more profiles there are
more chances for a close runner-up, so a margin threshold learned at pool 37 is not the right
threshold at pool 2. The live demo has TWO profiles. So calibration and evaluation must both
happen at pool size 2, or the operating point does not describe the product.

DESIGN (identity-disjoint, deterministic, no random draws)

  * 46 eligible infants, sorted, formed into 23 FIXED adjacent disjoint pairs.
  * Pairs split into two halves. Calibrate on half A, evaluate once on untouched half B.
    Then cross over: calibrate on B, evaluate once on untouched A.
  * Concatenate the two untouched evaluation halves for the final counts.
  * Calibration pools and evaluation pools are BOTH two-profile.

PREDECLARED SELECTION OBJECTIVE - fixed before any evaluation half was scored:

  Among calibration points with coverage >= 50%, maximise precision, then accepted-correct count.
  Separately report the best calibration point with precision >= 75%.

If no untouched point reaches 50% coverage at >= 75% precision, that is stated plainly. The
evaluation half is never used to choose a threshold.

Production thresholds are NOT changed by this tool.

Usage:  python tools/two_profile_operating_point.py
"""
from __future__ import annotations

import collections
import glob
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

import config       # noqa: E402
import encoders     # noqa: E402
import identity     # noqa: E402
import store        # noqa: E402

CORPUS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "experiments", "donateacry-corpus",
                      "donateacry_corpus_cleaned_and_updated_data")
MIN_RECORDINGS = 3
Z95 = 1.959963985

# Predeclared. Do not change these to make an evaluation number look better.
MIN_COVERAGE = 0.50
ALT_MIN_PRECISION = 0.75
ACCEPT_PCTS = tuple(range(5, 100, 5))
MARGIN_GRID = (0.02, 0.05, 0.0708, 0.10, 0.12, 0.16, 0.20, 0.25, 0.30)


def wilson_upper(x: int, n: int, z: float = Z95) -> float:
    """Upper limit of the Wilson score interval; valid when x == 0, unlike a normal
    approximation. Zero observed errors is not a zero error RATE."""
    if n == 0:
        return 1.0
    p = x / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / d
    return min(1.0, centre + half)


def load_raw(enc, files=None):
    files = sorted(files or glob.glob(os.path.join(CORPUS, "*", "*.wav")))
    if not files:
        print(f"No corpus at {CORPUS}", file=sys.stderr)
        return None
    raw = collections.defaultdict(dict)
    t0 = time.time()
    for i, p in enumerate(files):
        v = encoders.encode(enc, p)
        if v is not None:
            raw[os.path.basename(p)[:36].lower()][p] = v
        if i % 100 == 0:
            print(f"  ...{i}/{len(files)}", file=sys.stderr)
    print(f"  encoded in {time.time()-t0:.0f}s", file=sys.stderr)
    return dict(raw)


def common_recording_paths(left, right, minimum_recordings=MIN_RECORDINGS):
    """Return exact paths processed by both encoders, grouped by eligible identity."""
    common = {}
    for uid in sorted(set(left) & set(right)):
        paths = sorted(set(left[uid]) & set(right[uid]))
        if len(paths) >= minimum_recordings:
            common[uid] = paths
    return common


def prepare_matched_people(enc, raw, paths_by_uid, baseline):
    """Prepare vectors in a shared path order and return that order for parity checks."""
    people = {}
    ordered_paths = {}
    for uid in sorted(paths_by_uid):
        paths = list(paths_by_uid[uid])
        vectors = [raw[uid][path] for path in paths]
        people[uid] = list(encoders.prepare(enc, vectors, baseline))
        ordered_paths[uid] = paths
    return people, ordered_paths


def load_people(enc=None):
    enc = enc or encoders.MFCC87
    raw = load_raw(enc)
    if not raw:
        return None
    base = store.get_baseline(config.POPULATION_KEY)
    if not base:
        print("No population baseline. Run tools/build_baseline.py", file=sys.stderr)
        return None
    baseline = (
        (np.asarray(base["mu"]), np.asarray(base["sd"]))
        if encoders.needs_baseline(enc)
        else None
    )
    paths_by_uid = {
        uid: sorted(rows)
        for uid, rows in raw.items()
        if len(rows) >= MIN_RECORDINGS
    }
    people, _ = prepare_matched_people(enc, raw, paths_by_uid, baseline)
    return people


def pair_trials(pairs, people):
    """LOO within each two-profile pool. Pool size is ALWAYS 2."""
    out = []
    for a, b in pairs:
        for truth, other in ((a, b), (b, a)):
            for i in range(len(people[truth])):
                q = people[truth][i]
                own = [v for j, v in enumerate(people[truth]) if j != i]
                if not own:
                    continue
                s_own = float(np.mean([v @ q for v in own]))
                s_oth = float(np.mean([v @ q for v in people[other]]))
                top, top_s = (truth, s_own) if s_own >= s_oth else (other, s_oth)
                out.append({"truth": truth, "pred": top, "score": top_s,
                            "margin": abs(s_own - s_oth), "correct": top == truth,
                            "pool_size": 2})
    return out


def gated(trials, accept, margin_thr):
    mc = mw = ab = 0
    for t in trials:
        if t["score"] < accept or t["margin"] < margin_thr:
            ab += 1
        elif t["correct"]:
            mc += 1
        else:
            mw += 1
    return mc, mw, ab


def select(trials, min_coverage=MIN_COVERAGE, min_precision=None):
    """Threshold selection on CALIBRATION trials only, per the predeclared objective."""
    n = len(trials)
    if not n:
        return None
    scores = np.array([t["score"] for t in trials])
    best = None
    for pct in ACCEPT_PCTS:
        thr = float(np.percentile(scores, pct))
        for mth in MARGIN_GRID:
            a, b, _ = gated(trials, thr, mth)
            named = a + b
            if not named:
                continue
            cov, prec = named / n, a / named
            if min_precision is not None:
                if prec < min_precision:
                    continue
                key = (cov, a)                      # maximise coverage at that precision floor
            else:
                if cov < min_coverage:
                    continue
                key = (prec, a)                     # maximise precision, then correct count
            if best is None or key > best[0]:
                best = (key, thr, mth, cov, prec)
    return best


def evaluate(trials, accept, margin_thr, label):
    n = len(trials)
    mc, mw, ab = gated(trials, accept, margin_thr)
    named = mc + mw
    print(f"\n  {label}")
    print(f"    thresholds applied  : accept {accept:+.4f}  margin {margin_thr:.4f}")
    print(f"    total queries       : {n}")
    print(f"    named CORRECT       : {mc}")
    print(f"    named WRONG         : {mw}")
    print(f"    abstained           : {ab}")
    print(f"    coverage            : {named/n:.1%}" if n else "")
    if named:
        print(f"    precision when naming: {mc/named:.1%}  ({mc}/{named})")
        print(f"    Wilson 95% upper bound on wrong-name rate among named: "
              f"{wilson_upper(mw, named):.1%}")
    print(f"    Wilson 95% upper bound over ALL queries: {wilson_upper(mw, n):.1%}")
    return {"n": n, "correct": mc, "wrong": mw, "abstain": ab,
            "coverage": named / n if n else 0.0,
            "precision": mc / named if named else None, "named": named}


def run(enc: str, people=None, paths_by_uid=None) -> dict:
    people = people or load_people(enc)
    if not people:
        return {}
    uids = sorted(people)
    pairs = [(uids[i], uids[i + 1]) for i in range(0, len(uids) - 1, 2)]

    print("=" * 84)
    print(f" TWO-PROFILE OPERATING POINT - encoder {enc}")
    print(" (calibrated AND evaluated at pool size 2)")
    print("=" * 84)
    print(f"\n eligible infants        : {len(uids)}")
    print(f" fixed disjoint pairs    : {len(pairs)}")
    print(f" predeclared objective   : coverage >= {MIN_COVERAGE:.0%}, then max precision,")
    print(f"                           then max accepted-correct")
    print(f" alternative reported    : best point with precision >= {ALT_MIN_PRECISION:.0%}")
    print(f" production thresholds   : NOT modified by this tool")
    print(f" thresholds are per-encoder: MFCC values are NEVER reused for ECAPA (different scale)")

    half = len(pairs) // 2
    A, B = pairs[:half], pairs[half:]
    tA, tB = pair_trials(A, people), pair_trials(B, people)
    print(f"\n half A: {len(A)} pairs, {len(tA)} queries   |   "
          f"half B: {len(B)} pairs, {len(tB)} queries")

    # ── raw rank-1, reported separately and before any gate ──
    print("\n" + "=" * 84)
    print(" RAW TWO-PROFILE RANK-1 (no gates)")
    print("=" * 84)
    allt = tA + tB
    r1 = sum(t["correct"] for t in allt)
    print(f"\n   {r1}/{len(allt)} = {r1/len(allt):.1%}   (chance 50.0%)")
    print(f"   Wilson 95% upper bound on rank-1 error: "
          f"{wilson_upper(len(allt)-r1, len(allt)):.1%}")

    # ── crossover: calibrate on one half, evaluate ONCE on the untouched other ──
    print("\n" + "=" * 84)
    print(" CROSSOVER - thresholds chosen on one half, applied once to the untouched half")
    print("=" * 84)
    results, alt_results = [], []
    for name, cal_t, ev_t in (("A -> B", tA, tB), ("B -> A", tB, tA)):
        sel = select(cal_t)
        if sel is None:
            print(f"\n  {name}: NO calibration point reached {MIN_COVERAGE:.0%} coverage.")
            continue
        (_, thr, mth, cov, prec) = sel
        print(f"\n  calibration half of {name}: chose accept {thr:+.4f} margin {mth:.4f} "
              f"(cal coverage {cov:.1%}, cal precision {prec:.1%})")
        results.append(evaluate(ev_t, thr, mth, f"UNTOUCHED EVALUATION {name}"))

        sel2 = select(cal_t, min_precision=ALT_MIN_PRECISION)
        if sel2 is None:
            print(f"    (no calibration point reached precision >= {ALT_MIN_PRECISION:.0%})")
        else:
            (_, thr2, mth2, cov2, prec2) = sel2
            print(f"    alt objective (precision >= {ALT_MIN_PRECISION:.0%}): accept "
                  f"{thr2:+.4f} margin {mth2:.4f} (cal cov {cov2:.1%}, prec {prec2:.1%})")
            alt_results.append(evaluate(ev_t, thr2, mth2,
                                        f"UNTOUCHED EVALUATION {name} [alt objective]"))

    # ── concatenated untouched result ──
    def combine(rs, title):
        if not rs:
            return None
        n = sum(r["n"] for r in rs); c = sum(r["correct"] for r in rs)
        w = sum(r["wrong"] for r in rs); a = sum(r["abstain"] for r in rs)
        named = c + w
        print("\n" + "=" * 84)
        print(f" {title}")
        print("=" * 84)
        print(f"\n   total queries        : {n}")
        print(f"   named CORRECT        : {c}")
        print(f"   named WRONG          : {w}")
        print(f"   abstained            : {a}")
        print(f"   coverage             : {named/n:.1%}")
        if named:
            print(f"   precision when naming: {c/named:.1%}  ({c}/{named})")
            print(f"   Wilson 95% upper bound on wrong-name rate: {wilson_upper(w, named):.1%}")
        return {"coverage": named / n, "precision": c / named if named else 0.0,
                "n": n, "correct": c, "wrong": w, "named": named}

    main_res = combine(results, "CONCATENATED UNTOUCHED RESULT - predeclared objective")
    alt_res = combine(alt_results,
                      f"CONCATENATED UNTOUCHED RESULT - alt objective (precision >= "
                      f"{ALT_MIN_PRECISION:.0%})")

    # ── the direct answer product workstream asked for ──
    print("\n" + "=" * 84)
    print(" DIRECT ANSWER")
    print("=" * 84)
    hit = [r for r in (main_res, alt_res)
           if r and r["coverage"] >= MIN_COVERAGE and r["precision"] >= ALT_MIN_PRECISION]
    if hit:
        r = max(hit, key=lambda x: (x["precision"], x["coverage"]))
        print(f"\n ✅ An untouched two-profile point DOES reach >= {MIN_COVERAGE:.0%} coverage at")
        print(f"    >= {ALT_MIN_PRECISION:.0%} precision: coverage {r['coverage']:.1%}, "
              f"precision {r['precision']:.1%}, {r['correct']} correct / {r['wrong']} wrong "
              f"of {r['n']} queries.")
    else:
        print(f"\n ❌ NO untouched two-profile operating point reached {MIN_COVERAGE:.0%} coverage")
        print(f"    at >= {ALT_MIN_PRECISION:.0%} precision. Stated plainly rather than tuned on")
        print(f"    the evaluation half to force it.")
        for r, nm in ((main_res, "predeclared"), (alt_res, "alt")):
            if r:
                print(f"      {nm:12} -> coverage {r['coverage']:.1%}, "
                      f"precision {r['precision']:.1%}")

    print("\n" + "=" * 84)
    print(" ASSUMPTIONS AND LIMITS")
    print("=" * 84)
    print(f"""
 * identity = the 36-char device-UUID filename prefix; one family's phone assumed to be one
   infant. A shared device would merge identities and make these figures OPTIMISTIC.
 * recordings within an identity treated as independent; the corpus does not state whether they
   are separate sessions, so same-session snippets cannot be excluded - also OPTIMISTIC.
 * corpus audio is 8 kHz 2015 phone recordings. These are NOT demo-rig numbers and must never be
   quoted interchangeably with live-rig results (cross-channel measured -0.258).
 * only {len(uids)} infants have >= {MIN_RECORDINGS} recordings, so each half calibrates on a
   modest number of pairs. Threshold stability across the crossover is itself evidence.
 * production thresholds unchanged.
""")
    return {"encoder": enc, "uids": set(uids), "rank1": r1 / len(allt) if allt else 0.0,
            "rank1_n": len(allt), "rank1_correct": r1,
            "main": main_res, "alt": alt_res, "paths_by_uid": paths_by_uid}


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--encoders", default="both",
                    help="mfcc | cryceleb | both  (both = matched-identity comparison)")
    args = ap.parse_args()

    if args.encoders == "mfcc":
        run(encoders.MFCC87)
        return 0
    if args.encoders == "cryceleb":
        run(encoders.ECAPA_CRY)
        return 0

    files = sorted(glob.glob(os.path.join(CORPUS, "*", "*.wav")))
    mfcc_raw = load_raw(encoders.MFCC87, files)
    cry_raw = load_raw(encoders.ECAPA_CRY, files)
    if not mfcc_raw or not cry_raw:
        return 1
    common = common_recording_paths(mfcc_raw, cry_raw)
    if not common:
        return 1
    base = store.get_baseline(config.POPULATION_KEY)
    if not base:
        print("No population baseline. Run tools/build_baseline.py", file=sys.stderr)
        return 1
    mfcc_people, mfcc_paths = prepare_matched_people(
        encoders.MFCC87,
        mfcc_raw,
        common,
        (np.asarray(base["mu"]), np.asarray(base["sd"])),
    )
    cry_people, cry_paths = prepare_matched_people(
        encoders.ECAPA_CRY,
        cry_raw,
        common,
        None,
    )
    if mfcc_paths != cry_paths:
        raise RuntimeError("encoder comparison query paths are not identical")
    a = run(encoders.MFCC87, people=mfcc_people, paths_by_uid=mfcc_paths)
    b = run(encoders.ECAPA_CRY, people=cry_people, paths_by_uid=cry_paths)
    if a["rank1_n"] != b["rank1_n"]:
        raise RuntimeError("encoder comparison query counts are not identical")

    print("\n" + "=" * 84)
    print(" MATCHED HEAD-TO-HEAD - identical recordings, pairs, and protocol")
    print("=" * 84)
    print(f"\n   {'encoder':22} {'rank-1':>9} {'coverage':>9} {'precision':>10} "
          f"{'correct':>8} {'wrong':>7}")
    for r in (a, b):
        m = r.get("main") or {}
        print(f"   {r['encoder']:22} {r['rank1']:8.1%} "
              f"{m.get('coverage', 0):8.1%} {m.get('precision', 0):9.1%} "
              f"{m.get('correct', 0):8d} {m.get('wrong', 0):7d}")
    print(f"\n   identities compared: {len(a['uids'])}")
    print(f"   recordings compared: {sum(len(paths) for paths in mfcc_paths.values())}")
    print("   every query path is identical for both encoders")
    print("\n   A production switch requires the UNTOUCHED GATED result to improve, not just")
    print("      rank-1, and requires phone-channel calibration first. Corpus thresholds do not")
    print("      transfer to the live rig. No routing change is made here.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
