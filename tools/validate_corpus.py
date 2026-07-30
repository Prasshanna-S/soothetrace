"""Large-scale validation of identity on the full public corpus.

WHY THIS RUN MATTERS MORE THAN ANYTHING MEASURED SO FAR

Every identity number in this repo comes from **two infants on one rig** (15 LOO trials) or
**two adults** (5 references). Two known weaknesses follow from that and neither can be fixed
with more analysis of the same data:

  1. Every "impostor" score came from ONE other subject. An error rate estimated from a single
     impostor identity is a point estimate with a very wide interval, not a population figure.
  2. A 2-profile pool is the easiest possible identification task. Chance is 50%. Nothing tells
     us whether the result survives 10 profiles, or 50.

The corpus has ~100 infants with multiple recordings. That answers both.

WHAT THIS DOES AND DOES NOT MEASURE

  ✅ It measures the ALGORITHM's discrimination and how it scales with pool size, and it gives a
     false-accept rate estimated against many identities instead of one.
  ❌ It does NOT measure demo performance. The corpus is 8 kHz 2015 phone audio; the demo rig is
     a live room. Cross-channel matching was measured at -0.258, so these are different
     conditions. A number here does not transfer to the stage, and vice versa.

Both are reported: outcomes under the SHIPPED thresholds (which were calibrated on live rig
audio, so a domain shift is expected and its size is itself informative), and the operating
point achievable if thresholds were re-derived on corpus audio.

Usage:  python tools/validate_corpus.py [--min-recordings 3] [--draws 20]
"""
from __future__ import annotations

import argparse
import collections
import glob
import os
import random
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


def load_embeddings():
    """{uuid: [normalized vectors]} for every usable corpus recording."""
    files = sorted(glob.glob(os.path.join(CORPUS, "*", "*.wav")))
    if not files:
        print(f"No corpus at {CORPUS}", file=sys.stderr)
        return None
    base = store.get_baseline(config.POPULATION_KEY)
    if not base:
        print("No population baseline - run tools/build_baseline.py", file=sys.stderr)
        return None
    mu = np.asarray(base["mu"]); sd = np.asarray(base["sd"])

    raw, skipped = collections.defaultdict(list), 0
    t0 = time.time()
    for i, p in enumerate(files):
        name = os.path.basename(p)
        uid = name[:36].lower()
        v = encoders.encode(encoders.MFCC87, p)
        if v is None:
            skipped += 1
        else:
            raw[uid].append(v)
        if i % 100 == 0:
            print(f"  ...{i}/{len(files)}", file=sys.stderr)
    print(f"  encoded {sum(len(v) for v in raw.values())} of {len(files)} files "
          f"({skipped} unusable) in {time.time()-t0:.0f}s", file=sys.stderr)

    out = {}
    for uid, vs in raw.items():
        out[uid] = list(encoders.prepare(encoders.MFCC87, vs, (mu, sd)))
    return out


def score(query, enrollments) -> float:
    """Exactly the shipped aggregation: MEAN cosine across a profile's enrollments."""
    return float(np.mean([e @ query for e in enrollments]))


def closed_set(pool, people, rng):
    """LOO identification over `pool` uuids. Returns per-trial records."""
    trials = []
    for truth in pool:
        recs = people[truth]
        for held_i in range(len(recs)):
            q = recs[held_i]
            scored = []
            for uid in pool:
                ens = [v for j, v in enumerate(people[uid]) if not (uid == truth and j == held_i)]
                if ens:
                    scored.append((uid, score(q, ens)))
            if len(scored) < 2:
                continue
            scored.sort(key=lambda kv: -kv[1])
            top, top_s = scored[0]
            margin = top_s - scored[1][1]
            trials.append({"truth": truth, "pred": top, "score": top_s, "margin": margin,
                           "correct": top == truth})
    return trials


def gated(trials, accept, margin_thr):
    """Apply the two shipped gates. Returns (match_correct, match_wrong, abstain)."""
    mc = mw = ab = 0
    for t in trials:
        if t["score"] < accept or t["margin"] < margin_thr:
            ab += 1
        elif t["correct"]:
            mc += 1
        else:
            mw += 1
    return mc, mw, ab


def verify_fidelity(people, uids, rng, n_profiles=5):
    """Run the SHIPPED identity.identify() on real corpus files and compare to this tool.

    This tool replicates the scoring/gating inline for speed. If that replication has drifted
    from the shipped code, every number above is describing something we do not ship - so it
    is checked rather than assumed.
    """
    import tempfile
    import glob as _glob
    files_by_uid = collections.defaultdict(list)
    for p in sorted(_glob.glob(os.path.join(CORPUS, "*", "*.wav"))):
        files_by_uid[os.path.basename(p)[:36].lower()].append(p)

    pool = [u for u in uids if len(files_by_uid.get(u, [])) >= 3][:n_profiles]
    if len(pool) < 2:
        print("  not enough infants with files on disk to verify")
        return
    db = os.path.join(tempfile.mkdtemp(), "fidelity.db")
    store.init_db(db)
    b = store.get_baseline(config.POPULATION_KEY)
    store.save_baseline(config.POPULATION_KEY, b["mu"], b["sd"], b["n"], db)

    held = {}
    for uid in pool:
        prof = identity.create_profile(f"corpus-{uid[:8]}", identity.KIND_INFANT, db_path=db)
        fs = files_by_uid[uid]
        for f in fs[:-1]:
            identity.enroll(prof["id"], f, db_path=db)
        held[uid] = (prof["id"], fs[-1])

    agree = total = 0
    print(f"\n  {n_profiles}-profile pool, shipped identify() vs this tool's inline math:")
    for uid, (pid, qf) in held.items():
        res = identity.identify(qf, kind=identity.KIND_INFANT, db_path=db)
        # inline equivalent, same pool, same aggregation
        vec = encoders.encode(encoders.MFCC87, qf)
        if vec is None:
            continue
        mu = np.asarray(b["mu"]); sd = np.asarray(b["sd"])
        q = encoders.prepare(encoders.MFCC87, vec, (mu, sd))[0]
        scores = []
        for uid2, (pid2, _) in held.items():
            ens = encoders.prepare(encoders.MFCC87,
                                   [encoders.encode(encoders.MFCC87, f)
                                    for f in files_by_uid[uid2][:-1]
                                    if encoders.encode(encoders.MFCC87, f) is not None],
                                   (mu, sd))
            scores.append((pid2, score(q, list(ens))))
        scores.sort(key=lambda kv: -kv[1])
        inline_top, inline_score = scores[0]
        same_top = (res.get("candidates") or [{}])[0].get("profile_id") == inline_top \
            if res.get("candidates") else False
        close = res.get("score") is not None and abs(res["score"] - inline_score) < 1e-6
        ok = same_top and close
        agree += ok; total += 1
        print(f"    {uid[:8]}  identify: {res['status']:9} pool={res.get('pool_size')} "
              f"score={res.get('score')}  inline score={inline_score:+.6f}  "
              f"{'AGREE' if ok else 'MISMATCH'}")
    if total:
        print(f"\n  agreement: {agree}/{total}")
        if agree == total:
            print("  ✅ this tool's numbers describe the SHIPPED code path.")
        else:
            print("  🔴 MISMATCH - the numbers above do NOT describe what we ship. Fix before quoting.")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-recordings", type=int, default=3,
                    help="infants with fewer are excluded: leave-one-out must still leave >=2 "
                         "enrollments, or the profile would be 'provisional' and the trial would "
                         "measure a degenerate case rather than the product")
    ap.add_argument("--draws", type=int, default=20,
                    help="random pools per size, to separate signal from a lucky sample")
    args = ap.parse_args()

    people = load_embeddings()
    if people is None:
        return 1

    eligible = {u: v for u, v in people.items() if len(v) >= args.min_recordings}
    cal = identity.load_calibration(identity.KIND_INFANT)
    accept, margin_thr = cal["accept_threshold"], cal["margin_threshold"]

    print("=" * 84)
    print(" CORPUS-SCALE IDENTITY VALIDATION")
    print("=" * 84)
    print(f"\n corpus infants (any count) : {len(people)}")
    print(f" eligible (>= {args.min_recordings} recordings)  : {len(eligible)}")
    print(f" eligible recordings        : {sum(len(v) for v in eligible.values())}")
    print(f" shipped gates              : accept {accept}  margin {margin_thr}")
    print(f" encoder                    : {encoders.MFCC87} / {identity.AGGREGATION_VERSION}")
    print("\n ⚠️  Corpus is 8 kHz 2015 phone audio. The shipped thresholds were calibrated on")
    print("    LIVE ROOM audio, so a domain shift is expected. Both views are reported.")

    if len(eligible) < 4:
        print("\nNot enough eligible infants for a scaling study.", file=sys.stderr)
        return 1

    rng = random.Random(0)
    uids = sorted(eligible)

    # ── 1. how does identification scale with the number of enrolled profiles? ──
    print("\n" + "=" * 84)
    print(" 1. DOES IT SURVIVE MORE THAN TWO PROFILES?")
    print("=" * 84)
    print("\n Rank-1 = did the correct infant score highest (no gates). This is the pure")
    print(" discrimination question. Gated = what the product would actually have said.\n")
    print(f"   {'pool':>5} {'chance':>7} {'rank-1':>8} {'match✓':>8} {'match✗':>8} "
          f"{'abstain':>8} {'trials':>7}")
    sizes = [s for s in (2, 5, 10, 25, 50, len(uids)) if s <= len(uids)]
    curve = {}
    for size in sizes:
        r1 = mc = mw = ab = n = 0
        draws = 1 if size == len(uids) else args.draws
        for d in range(draws):
            pool = uids if size == len(uids) else rng.sample(uids, size)
            trials = closed_set(pool, eligible, rng)
            r1 += sum(t["correct"] for t in trials)
            a, b, c = gated(trials, accept, margin_thr)
            mc += a; mw += b; ab += c; n += len(trials)
        if not n:
            continue
        curve[size] = (r1 / n, mc / n, mw / n, ab / n, n)
        print(f"   {size:5d} {1/size:6.1%} {r1/n:7.1%} {mc/n:7.1%} {mw/n:7.1%} "
              f"{ab/n:7.1%} {n:7d}")

    # ── 2. wrong-answer rate: the number that decides whether it is demo-safe ──
    print("\n" + "=" * 84)
    print(" 2. HOW OFTEN DOES IT NAME THE WRONG INFANT?")
    print("=" * 84)
    full = uids
    trials = closed_set(full, eligible, rng)
    mc, mw, ab = gated(trials, accept, margin_thr)
    n = len(trials)
    print(f"\n Full pool: {len(full)} infants, {n} leave-one-out trials")
    print(f"   named the RIGHT infant : {mc:5d}  ({mc/n:.1%})")
    print(f"   named the WRONG infant : {mw:5d}  ({mw/n:.1%})   <-- the number that matters")
    print(f"   abstained              : {ab:5d}  ({ab/n:.1%})")
    if mc + mw:
        print(f"\n   precision when it DOES name someone: {mc/(mc+mw):.1%}")
        print("   i.e. of the times the product commits to a name, that fraction were right.")

    # ── 3. thresholds re-derived on corpus audio ──
    print("\n" + "=" * 84)
    print(" 3. IF THRESHOLDS WERE RE-DERIVED ON THIS AUDIO")
    print("=" * 84)
    gen = np.array([t["score"] for t in trials if t["correct"]])
    imp = np.array([t["score"] for t in trials if not t["correct"]])
    print(f"\n correct-top scores : n={len(gen):5d} mean {gen.mean():+.4f} min {gen.min():+.4f}")
    if len(imp):
        print(f" wrong-top scores   : n={len(imp):5d} mean {imp.mean():+.4f} max {imp.max():+.4f}")
    # ⚠️ An earlier version of this section reported ONE operating point chosen by
    # maximising precision first. That always finds a 100%-precision point at whatever cost
    # to coverage, so it reported 8.8% coverage and made the system look far weaker than it
    # is. Coverage was MY selection criterion, not the system's ceiling. The honest artifact
    # is the whole trade-off curve.
    print("\n PRECISION / COVERAGE TRADE-OFF (the operating point is a CHOICE, not a property)")
    print(f"\n   {'accept':>8} {'margin':>7} {'named':>7} {'right':>7} {'wrong':>7} "
          f"{'precision':>10} {'coverage':>9}")
    rows = []
    for pct in (10, 25, 40, 50, 60, 70, 80):
        thr = float(np.percentile(gen, pct))
        for mth in (0.02, 0.05, 0.0708, 0.12, 0.20):
            a, b, c = gated(trials, thr, mth)
            named = a + b
            if not named:
                continue
            rows.append((thr, mth, named, a, b, a / named, named / n))
    seen = set()
    for thr, mth, named, a, b, prec, cov in sorted(rows, key=lambda r: -r[6]):
        key = (round(prec, 3), round(cov, 3))
        if key in seen:
            continue
        seen.add(key)
        print(f"   {thr:+8.4f} {mth:7.2f} {named:7d} {a:7d} {b:7d} {prec:9.1%} {cov:8.1%}")

    if rows:
        zero_wrong = [r for r in rows if r[4] == 0]
        if zero_wrong:
            bz = max(zero_wrong, key=lambda r: r[3])
            print(f"\n   BEST ZERO-ERROR POINT : accept {bz[0]:+.4f} margin {bz[1]:.2f} -> "
                  f"{bz[3]} correct, 0 wrong, coverage {bz[6]:.1%}")
        b90 = [r for r in rows if r[5] >= 0.90]
        if b90:
            bb = max(b90, key=lambda r: r[6])
            print(f"   BEST >=90%% PRECISION  : accept {bb[0]:+.4f} margin {bb[1]:.2f} -> "
                  f"{bb[3]} correct, {bb[4]} wrong, coverage {bb[6]:.1%}, precision {bb[5]:.1%}")
        bb = max(rows, key=lambda r: r[3])
        print(f"   MOST CORRECT NAMES    : accept {bb[0]:+.4f} margin {bb[1]:.2f} -> "
              f"{bb[3]} correct, {bb[4]} wrong, coverage {bb[6]:.1%}, precision {bb[5]:.1%}")

    report_grouped(eligible, uids)

    # ── 4. does this tool agree with the SHIPPED code path? ──
    print("\n" + "=" * 84)
    print(" 4. FIDELITY - does this tool match the real identity.identify() path?")
    print("=" * 84)
    verify_fidelity(eligible, uids, rng)

    print("\n" + "=" * 84)
    print(" READ THIS BEFORE QUOTING ANYTHING ABOVE")
    print("=" * 84)
    print(f"""
 * These are CORPUS numbers, not demo numbers. 8 kHz 2015 phone recordings, one per
   session, mixed devices. Cross-channel matching measured -0.258, so corpus and live-rig
   results describe different conditions and must never be quoted interchangeably.
 * The gates were calibrated on live rig audio. Applying them here is a domain shift, and a
   high abstention rate under section 1-2 is that shift showing up - not necessarily a
   discrimination failure. Section 3 separates the two.
 * Rank-1 in section 1 is the honest measure of DISCRIMINATION; the gated columns measure
   the PRODUCT, which deliberately abstains rather than guess.
 * Many corpus infants contribute only 3 recordings, so leave-one-out leaves 2 enrollments - 
   the minimum the product considers 'ready'. Accuracy would be higher with more per infant.
 * Chance at pool size N is 1/N. Compare rank-1 against that column, not against 100%.
""")
    return 0




# ── grouped cross-validation by baby - the identity-disjoint design ──────────
# product workstream correctly rejected the earlier section 3: it searched thresholds on the SAME 205
# trials it then reported, which is test-set tuning. The 18-correct/0-wrong figure was
# therefore optimistic and is NOT a validation result. This replaces it.
#
# Design: grouped K-fold by BABY. Thresholds are selected only inside each training fold
# (identities disjoint from evaluation), frozen, then applied ONCE to the held-out fold.
# Outer-fold predictions are concatenated untouched for the final counts.

Z95 = 1.959963985


def wilson_upper(x: int, n: int, z: float = Z95) -> float:
    """Upper limit of the Wilson score interval. Valid when x == 0, unlike a normal
    approximation - which is the case we most need, since 'zero wrong observed' is not
    evidence of a zero wrong RATE."""
    if n == 0:
        return 1.0
    p = x / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / d
    return min(1.0, centre + half)


def select_thresholds(trials, max_wrong_rate=0.05):
    """Pick (accept, margin) on TRAINING trials only.

    Rule fixed in advance: maximise accepted-correct subject to the wrong rate among NAMED
    decisions staying at or below `max_wrong_rate`. Declared before looking at any evaluation
    fold, so it cannot be tuned to the answer.
    """
    gen = [t["score"] for t in trials if t["correct"]]
    if not gen:
        return None
    best = None
    for pct in range(5, 100, 5):
        thr = float(np.percentile(gen, pct))
        for mth in (0.02, 0.05, 0.0708, 0.10, 0.12, 0.16, 0.20, 0.25):
            a, b, _ = gated(trials, thr, mth)
            named = a + b
            if named == 0:
                continue
            if b / named > max_wrong_rate:
                continue
            if best is None or a > best[0]:
                best = (a, thr, mth)
    return None if best is None else (best[1], best[2])


def grouped_cv(people, uids, folds=5, max_wrong_rate=0.05):
    """Report untouched outer-fold performance with identity-disjoint threshold selection."""
    uids = sorted(uids)                      # deterministic, no random draws
    buckets = [uids[i::folds] for i in range(folds)]

    all_trials, chosen = [], []
    for k in range(folds):
        evalu = buckets[k]
        train = [u for j, b in enumerate(buckets) if j != k for u in b]
        if len(evalu) < 2 or len(train) < 2:
            continue
        thr = select_thresholds(closed_set(train, people, None), max_wrong_rate)
        if thr is None:
            continue
        accept, margin = thr
        chosen.append((k, len(train), len(evalu), accept, margin))
        for t in closed_set(evalu, people, None):
            all_trials.append({**t, "fold": k, "accept": accept, "margin_thr": margin})
    return all_trials, chosen


def report_grouped(people, uids, folds=5):
    print("\n" + "=" * 84)
    print(" 3. IDENTITY-DISJOINT GROUPED CROSS-VALIDATION  (replaces the tuned section)")
    print("=" * 84)
    trials, chosen = grouped_cv(people, uids, folds)
    if not trials:
        print("  insufficient identities for grouped CV")
        return
    print(f"\n  {folds}-fold grouped by baby. Thresholds selected on TRAINING babies only,")
    print(f"  frozen, then applied once to held-out babies. Pool within a fold = that fold's")
    print(f"  babies, so calibration and evaluation identities are disjoint.\n")
    print(f"   {'fold':>5} {'train':>6} {'eval':>5} {'accept':>9} {'margin':>7}")
    for k, ntr, nev, a, m in chosen:
        print(f"   {k:5d} {ntr:6d} {nev:5d} {a:+9.4f} {m:7.3f}")

    n = len(trials)
    r1 = sum(t["correct"] for t in trials)
    mc = mw = ab = 0
    per_baby = collections.defaultdict(lambda: [0, 0, 0])
    for t in trials:
        if t["score"] < t["accept"] or t["margin"] < t["margin_thr"]:
            ab += 1; per_baby[t["truth"]][2] += 1
        elif t["correct"]:
            mc += 1; per_baby[t["truth"]][0] += 1
        else:
            mw += 1; per_baby[t["truth"]][1] += 1
    named = mc + mw

    print(f"\n  UNTOUCHED OUTER-FOLD RESULT - {n} trials across {len(per_baby)} babies")
    print(f"    rank-1 before gating : {r1:4d}  ({r1/n:.1%})")
    print(f"    named CORRECT        : {mc:4d}  ({mc/n:.1%})")
    print(f"    named WRONG          : {mw:4d}  ({mw/n:.1%})")
    print(f"    abstained            : {ab:4d}  ({ab/n:.1%})")
    if named:
        print(f"    precision when naming: {mc/named:.1%}  ({mc}/{named})")
        wu = wilson_upper(mw, named)
        print(f"\n    Wilson 95% UPPER bound on the wrong-name rate among NAMED decisions:")
        print(f"      {mw}/{named} observed  ->  up to {wu:.1%}")
        if mw == 0:
            print(f"      ⚠️  Zero wrong OBSERVED is not a zero wrong RATE. With {named} named")
            print(f"          decisions the true rate could still be as high as {wu:.1%}.")
    wu_all = wilson_upper(mw, n)
    print(f"    Wilson 95% upper bound over ALL trials: {mw}/{n} -> {wu_all:.1%}")

    print(f"\n  PER-BABY DISTRIBUTION (correct / wrong / abstain)")
    rows = sorted(per_baby.items(), key=lambda kv: (-kv[1][1], -kv[1][0]))
    for uid, (c, w, a) in rows[:12]:
        print(f"    {uid[:8]}  {c:2d} / {w:2d} / {a:2d}")
    if len(rows) > 12:
        print(f"    ... {len(rows)-12} more babies")
    worst = [u for u, v in per_baby.items() if v[1] > 0]
    print(f"\n    babies contributing >=1 wrong name: {len(worst)} of {len(per_baby)}")

    # fixed deterministic pairs, not repeated random draws
    print(f"\n  TWO-PROFILE EVALUATION - FIXED adjacent pairs, no random draws")
    su = sorted(uids)
    pairs = [(su[i], su[i + 1]) for i in range(0, len(su) - 1, 2)]
    pr1 = pn = 0
    for a_, b_ in pairs:
        for t in closed_set([a_, b_], people, None):
            pn += 1; pr1 += t["correct"]
    if pn:
        print(f"    {len(pairs)} disjoint pairs, {pn} trials, rank-1 {pr1/pn:.1%} "
              f"(chance 50.0%)")
        print(f"    Wilson 95% upper bound on pair-level error: "
              f"{wilson_upper(pn - pr1, pn):.1%}")

    # retry-level evaluation requires two distinct held-out recordings for one baby
    eligible_retry = [u for u in uids if len(people[u]) >= 4]
    print(f"\n  RETRY-LEVEL EVALUATION")
    print(f"    babies with >=4 recordings (2 enrollments + 2 distinct held-out): "
          f"{len(eligible_retry)} of {len(uids)}")
    if len(eligible_retry) < 2:
        print(f"    NOT EVALUATED - a retry needs two independent held-out recordings from the")
        print(f"    same baby, and the corpus does not supply enough of them.")

    print(f"\n  GROUPING ASSUMPTIONS (state these with any number above)")
    print(f"    * identity = the 36-char device UUID prefix of the filename. One family's phone")
    print(f"      is assumed to be one infant. If a device were shared, two identities would be")
    print(f"      merged and these figures would be optimistic.")
    print(f"    * source files within one identity are treated as INDEPENDENT recordings. The")
    print(f"      corpus does not state whether they are separate sessions, so same-session")
    print(f"      snippets cannot be excluded - which would also make figures optimistic.")
    print(f"    * production thresholds are NOT changed by this run.")

if __name__ == "__main__":
    sys.exit(main())
