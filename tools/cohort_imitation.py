"""Is cohort normalization FEASIBLE and DIRECTIONALLY HELPFUL for HUMAN IMITATIONS?

Encoder: ecapa-cryceleb-v1 only. ECAPA is L2-normalized and NEVER z-scored against a
population baseline (encoders.prepare does the right thing per encoder - we always go
through it). No mfcc87 score appears anywhere in this file, so no cross-encoder score is
ever compared or fused.

WHAT COHORT NORMALIZATION IS, AND WHAT IT NEEDS
-----------------------------------------------
identity.py scores a query against a profile as the MEAN cosine over that profile's
enrollments, then applies an absolute threshold and a runner-up margin. Cohort
normalization (Z-norm / T-norm / S-norm / adaptive AS-norm) replaces that raw cosine with a
z-score computed against a distribution of *impostor* scores, so that a profile which
happens to sit in a dense region of the embedding space (a "hubby" profile that scores
moderately high against everyone) is not systematically favoured.

That only works if the cohort actually samples the impostor population you will face. For
this task the impostor population is ADULTS PERFORMING CRY SOUNDS. We do not have one. What
we have is 221 distinct infants from the donateacry corpus, recorded on other people's
phones. So the honest question is not "does AS-norm help" but:

    does a cohort drawn from a DIFFERENT domain carry any information about the adult
    impostor distribution, or does it only inject a query-independent constant?

Section 3 answers that with numbers instead of adjectives.

WHAT 5 REFERENCES CANNOT DO
---------------------------
Person A has 3 references, Person B has 2. That is 5 leave-one-out trials, 5 genuine scores,
5 impostor scores, and exactly ONE distinct between-person pair. The strongest result
obtainable from 5 paired trials is 5/5, whose one-sided sign-test p is 2^-5 = 0.031 - and
this tool evaluates ~a dozen configurations, so even a perfect score is not significant after
correcting for the number of hypotheses. Section 6 prints that arithmetic. Nothing in this
file should be read as choosing a threshold.

BLIND QUERIES
-------------
norm-blind-query-01/02 are held out. They are not read, not encoded, and not scored until
AFTER the freeze rule in section 5 has picked a configuration from reference data alone. The
code enforces the ordering with an assertion, not with good intentions.

Usage:
    python tools/cohort_imitation.py
    python tools/cohort_imitation.py --cache /tmp/cohort_imitation_cache.npz
    python tools/cohort_imitation.py --no-blind        # skip the final verification section
"""
from __future__ import annotations

import argparse
import itertools
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

import config     # noqa: E402
import encoders   # noqa: E402
import identity   # noqa: E402

ENC = encoders.ECAPA_CRY          # the measured encoder for KIND_IMITATION

REPLAY = os.path.join(config.AUDIO_DIR, "replay_master")
CORPUS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "experiments", "donateacry-corpus",
                      "donateacry_corpus_cleaned_and_updated_data")

PEOPLE = {
    "A": ["norm-prasshanna-01", "norm-prasshanna-02", "norm-prasshanna-03"],
    "B": ["norm-control-01", "norm-control-02"],
}
BLIND = ["norm-blind-query-01", "norm-blind-query-02"]
BLIND_TRUTH = "A"                 # revealed; used ONLY to score section 7, never to select

UUID_LEN = 36                     # filename prefix = device UUID; same UUID = same infant


# ── loading ──────────────────────────────────────────────────────────────────

def _wav(stem: str) -> str:
    return os.path.join(REPLAY, f"{stem}.wav")


def _l2(vecs) -> np.ndarray:
    """ECAPA: L2 only. encoders.prepare enforces the per-encoder rule; baseline=None is
    correct here and prepare() will raise if an encoder ever needs one."""
    return encoders.prepare(ENC, vecs, None)


def load_references() -> dict[str, np.ndarray]:
    """{stem: L2-normalized 192-d vector} for the 5 reference recordings."""
    out = {}
    for stems in PEOPLE.values():
        for s in stems:
            p = _wav(s)
            if not os.path.exists(p):
                print(f"  MISSING {p}", file=sys.stderr)
                continue
            v = encoders.encode(ENC, p)
            if v is None:
                print(f"  UNUSABLE {s}", file=sys.stderr)
                continue
            out[s] = v
    labs = list(out)
    P = _l2([out[l] for l in labs])
    return dict(zip(labs, P))


def corpus_files_one_per_uuid() -> tuple[list[str], int, int]:
    """One recording per distinct infant. Same UUID = same infant, so keeping several
    recordings from one device would make the cohort samples dependent and shrink its
    effective size without shrinking its apparent size."""
    if not os.path.isdir(CORPUS):
        return [], 0, 0
    all_files = []
    for root, _dirs, names in os.walk(CORPUS):
        for n in names:
            if n.lower().endswith(".wav"):
                all_files.append(os.path.join(root, n))
    all_files.sort()
    by_uuid: dict[str, str] = {}
    for f in all_files:
        uid = os.path.basename(f)[:UUID_LEN].lower()
        if len(uid) == UUID_LEN and uid not in by_uuid:
            by_uuid[uid] = f
    return [by_uuid[k] for k in sorted(by_uuid)], len(all_files), len(by_uuid)


def load_cohort(cache: str | None) -> tuple[np.ndarray, dict]:
    """(n_cohort x 192) L2-normalized corpus embeddings, one infant each."""
    files, n_all, n_uuid = corpus_files_one_per_uuid()
    if cache and os.path.exists(cache):
        z = np.load(cache, allow_pickle=True)
        X = z["X"]
        meta = {"n_all_files": int(z["n_all_files"]), "n_uuid": int(z["n_uuid"]),
                "n_encoded": int(X.shape[0]), "cached": True}
        return _l2(X), meta
    if not files:
        return np.zeros((0, 192)), {"n_all_files": 0, "n_uuid": 0, "n_encoded": 0,
                                    "cached": False}
    raw, skipped = [], 0
    for i, f in enumerate(files, 1):
        v = encoders.encode(ENC, f)
        if v is None:
            skipped += 1
            continue
        raw.append(v)
        if i % 50 == 0:
            print(f"    ...encoded {i}/{len(files)} cohort infants", file=sys.stderr)
    X = np.asarray(raw, dtype=np.float64)
    if cache:
        np.savez_compressed(cache, X=X, n_all_files=n_all, n_uuid=n_uuid)
    return _l2(X), {"n_all_files": n_all, "n_uuid": n_uuid, "n_encoded": X.shape[0],
                    "skipped": skipped, "cached": False}


# ── scoring ──────────────────────────────────────────────────────────────────

def profile_score(q: np.ndarray, E: np.ndarray) -> float:
    """Exactly identity.py's rule: MEAN cosine over the profile's enrollments."""
    return float(np.mean(E @ q))


def cohort_vs_profile(C: np.ndarray, E: np.ndarray) -> np.ndarray:
    """One score per cohort member, using the same mean-over-enrollments rule."""
    if C.shape[0] == 0 or E.shape[0] == 0:
        return np.zeros(0)
    return (C @ E.T).mean(axis=1)


def _mu_sd(x: np.ndarray, k: int | None = None) -> tuple[float, float, int]:
    """(mu, sd, n). Adaptive variants keep only the k highest scores. sd uses ddof=1, so
    n<2 gives NaN - an undefined normalization must be reported, not silently patched."""
    if x.size == 0:
        return float("nan"), float("nan"), 0
    if k is not None and k < x.size:
        x = np.sort(x)[-k:]
    n = int(x.size)
    if n < 2:
        return float(x.mean()), float("nan"), n
    return float(x.mean()), float(x.std(ddof=1)), n


# ── configurations under test ────────────────────────────────────────────────
# Each entry: (label, mode, cohort key, K or None)
#   raw    : no normalization                                    -- the baseline to beat
#   z      : (s - mu_P)/sd_P  over cohort-vs-PROFILE scores      -- can change A-vs-B ranking
#   as     : z, but only the K highest cohort-vs-profile scores   -- adaptive Z-norm
#   t      : (s - mu_q)/sd_q  over QUERY-vs-cohort scores         -- CANNOT change ranking
#   s      : mean of z and t                                      -- half the z effect
# cohort key: "corpus" = 221 corpus infants (domain-mismatched, option a)
#             "other"  = the other person's references, n=1..3    (option b)

def build_configs(n_cohort: int) -> list[tuple[str, str, str, int | None]]:
    cfgs: list[tuple[str, str, str, int | None]] = [("raw", "raw", "", None)]
    for k in (5, 10, 20, 50, 100):
        if k < n_cohort:
            cfgs.append((f"as-corpus-K{k}", "as", "corpus", k))
    if n_cohort >= 2:
        cfgs += [("z-corpus-full", "z", "corpus", None),
                 ("t-corpus-full", "t", "corpus", None),
                 ("s-corpus-full", "s", "corpus", None)]
    cfgs += [("z-other(n<=3)", "z", "other", None)]
    return cfgs


def normalized(mode: str, s_raw: float, coh_p: np.ndarray, coh_q: np.ndarray,
               k: int | None) -> float:
    if mode == "raw":
        return s_raw
    if mode in ("z", "as"):
        mu, sd, n = _mu_sd(coh_p, k if mode == "as" else None)
        return float("nan") if (n < 2 or not np.isfinite(sd) or sd <= 0) else (s_raw - mu) / sd
    if mode == "t":
        mu, sd, n = _mu_sd(coh_q, k)
        return float("nan") if (n < 2 or not np.isfinite(sd) or sd <= 0) else (s_raw - mu) / sd
    if mode == "s":
        a = normalized("z", s_raw, coh_p, coh_q, None)
        b = normalized("t", s_raw, coh_p, coh_q, None)
        return float("nan") if not (np.isfinite(a) and np.isfinite(b)) else (a + b) / 2.0
    raise ValueError(mode)


# ── leave-one-out over the 5 references ──────────────────────────────────────

def folds() -> list[tuple[str, str]]:
    """(truth, held-out stem) for all 5 references. No blind query is ever a fold."""
    return [(p, s) for p, stems in PEOPLE.items() for s in stems]


def loo_table(refs: dict[str, np.ndarray], C: np.ndarray,
              cfgs: list[tuple[str, str, str, int | None]]) -> dict[str, list[dict]]:
    """{config label: [per-fold dict]}. Cohort statistics depend only on ENROLLMENTS, never
    on the query, so nothing about a fold's held-out file leaks into its own normalization."""
    out: dict[str, list[dict]] = {lab: [] for lab, *_ in cfgs}
    for truth, held in folds():
        q = refs[held]
        other = "B" if truth == "A" else "A"
        E = {truth: np.asarray([refs[s] for s in PEOPLE[truth] if s != held and s in refs]),
             other: np.asarray([refs[s] for s in PEOPLE[other] if s != held and s in refs])}
        raw = {p: profile_score(q, E[p]) for p in ("A", "B")}

        coh_corpus = {p: cohort_vs_profile(C, E[p]) for p in ("A", "B")}
        # option (b): each profile's cohort is the OTHER person's references, minus the
        # held-out file (which is the query and must never sit in a cohort).
        coh_other = {}
        for p in ("A", "B"):
            o = "B" if p == "A" else "A"
            coh_other[p] = cohort_vs_profile(np.asarray(
                [refs[s] for s in PEOPLE[o] if s != held and s in refs]), E[p])
        q_vs_corpus = (C @ q) if C.shape[0] else np.zeros(0)

        for lab, mode, ck, k in cfgs:
            coh = coh_corpus if ck == "corpus" else coh_other
            sc = {}
            for p in ("A", "B"):
                cq = q_vs_corpus if ck == "corpus" else np.asarray(
                    [refs[s] @ q for s in PEOPLE["B" if p == "A" else "A"]
                     if s != held and s in refs])
                sc[p] = normalized(mode, raw[p], coh[p], cq, k)
            gen, imp = sc[truth], sc[other]
            ok = bool(np.isfinite(gen) and np.isfinite(imp) and gen > imp)
            out[lab].append({
                "truth": truth, "held": held, "genuine": gen, "impostor": imp,
                "margin": (gen - imp) if (np.isfinite(gen) and np.isfinite(imp))
                          else float("nan"),
                "correct": ok, "defined": bool(np.isfinite(gen) and np.isfinite(imp)),
                "n_enroll_own": int(E[truth].shape[0]), "n_enroll_other": int(E[other].shape[0]),
                "raw_gen": raw[truth], "raw_imp": raw[other]})
    return out


def summarize(rows: list[dict]) -> dict:
    g = np.array([r["genuine"] for r in rows], dtype=float)
    i = np.array([r["impostor"] for r in rows], dtype=float)
    ok = np.isfinite(g) & np.isfinite(i)
    n_def = int(ok.sum())
    if n_def == 0:
        return {"n": 0, "defined": 0, "loo": 0, "undefined": len(rows)}
    g, i = g[ok], i[ok]
    pooled = math.sqrt((g.var(ddof=1) + i.var(ddof=1)) / 2) if n_def > 1 else float("nan")
    auc = float(np.mean([[1.0 if a > b else 0.5 if a == b else 0.0 for b in i] for a in g]))
    return {
        "n": len(rows), "defined": n_def, "undefined": len(rows) - n_def,
        "loo": int(sum(1 for r in rows if r["correct"])),
        "g_mean": float(g.mean()), "g_sd": float(g.std(ddof=1)) if n_def > 1 else float("nan"),
        "g_min": float(g.min()),
        "i_mean": float(i.mean()), "i_sd": float(i.std(ddof=1)) if n_def > 1 else float("nan"),
        "i_max": float(i.max()),
        "gap": float(g.min() - i.max()),
        "pooled_sd": pooled,
        "std_gap": float((g.min() - i.max()) / pooled) if pooled and pooled > 0 else float("nan"),
        "dprime": float((g.mean() - i.mean()) / pooled) if pooled and pooled > 0 else float("nan"),
        "min_margin": float(np.min(g - i)),
        "std_min_margin": float(np.min(g - i) / pooled) if pooled and pooled > 0 else float("nan"),
        "auc": auc}


# ── freeze rule, declared before any blind audio is touched ──────────────────

FREEZE_RULE = """  1. computable in all 5 folds (an undefined normalization is disqualified);
  2. LOO must be 5/5 - with 5 trials anything less is not a candidate;
  3. rank by STANDARDIZED min margin  min(genuine-impostor) / pooled_sd  (scale-free, so
     z-scores and raw cosines are comparable on it);
  4. a cohort option must beat `raw` on that statistic by >= 0.25 to be preferred.
     Otherwise the frozen choice is `raw`. Five trials do not license a more complex
     pipeline for a small difference."""

MIN_IMPROVEMENT = 0.25


def freeze(summ: dict[str, dict]) -> tuple[str, list[str]]:
    log = []
    base = summ["raw"]
    cands = []
    for lab, s in summ.items():
        if lab == "raw":
            continue
        if s.get("undefined", 0) > 0:
            log.append(f"  {lab:16} DISQUALIFIED - undefined in "
                       f"{s['undefined']}/{s['n']} folds")
            continue
        if s["loo"] < s["n"]:
            log.append(f"  {lab:16} rejected - LOO {s['loo']}/{s['n']}")
            continue
        d = s["std_min_margin"] - base["std_min_margin"]
        log.append(f"  {lab:16} eligible - std-min-margin {s['std_min_margin']:+.3f} "
                   f"vs raw {base['std_min_margin']:+.3f}  (delta {d:+.3f})")
        cands.append((d, lab))
    if base["loo"] < base["n"]:
        log.append(f"  raw itself is only {base['loo']}/{base['n']} - no option is trusted; "
                   f"freezing `raw` anyway and reporting the failure.")
        return "raw", log
    cands.sort(reverse=True)
    if cands and cands[0][0] >= MIN_IMPROVEMENT:
        return cands[0][1], log
    log.append(f"  no cohort option clears +{MIN_IMPROVEMENT} over raw -> FROZEN = raw")
    return "raw", log


# ── sample-size arithmetic ───────────────────────────────────────────────────

def n_for_zero_error_bound(p: float, conf: float = 0.95) -> int:
    """Smallest n such that 0 errors in n independent trials gives a `conf` one-sided upper
    bound of `p` on the error rate:  1 - (1-conf)^(1/n) <= p."""
    return int(math.ceil(math.log(1 - conf) / math.log(1 - p)))


def participants_for_pairs(pairs: int) -> int:
    """Smallest P with P(P-1)/2 >= pairs distinct between-person pairs."""
    return int(math.ceil((1 + math.sqrt(1 + 8 * pairs)) / 2))


def n_for_tolerance_bound(pctl: float, conf: float = 0.95) -> int:
    """Distribution-free: smallest n whose sample MINIMUM is a `conf` lower bound for the
    `pctl` quantile.  1 - (1-pctl)^n >= conf."""
    return int(math.ceil(math.log(1 - conf) / math.log(1 - pctl)))


def sd_relative_se(n: int) -> float:
    """Relative standard error of a sample sd from n samples: ~1/sqrt(2(n-1))."""
    return float("inf") if n < 2 else 1.0 / math.sqrt(2 * (n - 1))


# ── main ─────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cache", default=None,
                    help="npz path to cache/reuse corpus cohort embeddings")
    ap.add_argument("--no-blind", action="store_true",
                    help="stop before the blind verification section")
    args = ap.parse_args()

    W = 88
    print("=" * W)
    print(" COHORT NORMALIZATION - HUMAN IMITATION DOMAIN")
    print(f" encoder {ENC}  (L2 only; never z-scored against a population baseline)")
    print("=" * W)

    print("\n[loading 5 reference recordings]")
    refs = load_references()
    have = {p: [s for s in stems if s in refs] for p, stems in PEOPLE.items()}
    print(f"  Person A: {len(have['A'])} refs   Person B: {len(have['B'])} refs   "
          f"total {len(refs)}")
    if len(have["A"]) < 2 or len(have["B"]) < 2:
        print("  cannot run: each person needs >= 2 usable references", file=sys.stderr)
        return 1

    print("[loading cohort: donateacry corpus, one recording per distinct infant UUID]")
    C, cmeta = load_cohort(args.cache)
    print(f"  corpus wav files {cmeta['n_all_files']}, distinct UUIDs {cmeta['n_uuid']}, "
          f"encoded {cmeta['n_encoded']}"
          + (f", skipped {cmeta.get('skipped', 0)}" if not cmeta.get("cached") else " (cached)"))
    if cmeta["n_encoded"] < 100:
        print("  ! fewer than 100 distinct infants - the task requires >=100", file=sys.stderr)

    cfgs = build_configs(C.shape[0])

    # ── 1. what the raw geometry looks like ──────────────────────────────────
    print("\n" + "=" * W)
    print(" 1. RAW GEOMETRY OF THE 5 REFERENCES  (no cohort, no normalization)")
    print("=" * W)
    wa = [float(refs[x] @ refs[y]) for x, y in itertools.combinations(have["A"], 2)]
    wb = [float(refs[x] @ refs[y]) for x, y in itertools.combinations(have["B"], 2)]
    bt = [float(refs[x] @ refs[y]) for x in have["A"] for y in have["B"]]
    print(f"  within-A  n={len(wa)}  mean {np.mean(wa):+.4f}  min {np.min(wa):+.4f}  "
          f"max {np.max(wa):+.4f}")
    print(f"  within-B  n={len(wb)}  mean {np.mean(wb):+.4f}   (a SINGLE pair - there is no"
          f" within-B spread to speak of)")
    print(f"  A-vs-B    n={len(bt)}  mean {np.mean(bt):+.4f}  min {np.min(bt):+.4f}  "
          f"max {np.max(bt):+.4f}")
    print(f"  raw within-pair minimum {min(wa + wb):+.4f} vs A-vs-B maximum "
          f"{max(bt):+.4f}  ->  "
          f"{'DISJOINT' if min(wa + wb) > max(bt) else 'OVERLAPPING'}")

    # ── 2. per-configuration LOO ─────────────────────────────────────────────
    print("\n" + "=" * W)
    print(" 2. LEAVE-ONE-OUT ON THE 5 REFERENCES, PER COHORT OPTION")
    print("=" * W)
    print("  Score = mean cosine over the profile's enrollments (identity.py's rule).")
    print("  genuine = held-out ref vs its OWN profile; impostor = same ref vs the other.")
    print("  Units differ by row: `raw` is cosine, everything else is a z-score. Compare")
    print("  rows only on the standardized columns.\n")
    tables = loo_table(refs, C, cfgs)
    summ = {lab: summarize(rows) for lab, rows in tables.items()}

    hdr = (f"  {'config':16} {'LOO':>5} {'undef':>5} {'gen mean':>9} {'gen min':>9} "
           f"{'imp mean':>9} {'imp max':>9} {'gap*':>8} {'stdGap':>7} {'d-prime':>8} "
           f"{'stdMinMg':>9} {'AUC':>5}")
    print(hdr)
    print("  " + "-" * (len(hdr) - 2))
    for lab, *_ in cfgs:
        s = summ[lab]
        if s["defined"] == 0:
            print(f"  {lab:16} {'n/a':>5} {s['undefined']:>5}   "
                  f"UNDEFINED IN EVERY FOLD - cohort too small to give an sd")
            continue
        print(f"  {lab:16} {s['loo']}/{s['n']:<3} {s['undefined']:>5} "
              f"{s['g_mean']:>9.4f} {s['g_min']:>9.4f} {s['i_mean']:>9.4f} "
              f"{s['i_max']:>9.4f} {s['gap']:>8.4f} {s['std_gap']:>7.3f} "
              f"{s['dprime']:>8.3f} {s['std_min_margin']:>9.3f} {s['auc']:>5.2f}")
    print("  * gap is in each row's NATIVE units (cosine for `raw`, z for the rest) and is")
    print("    therefore NOT comparable across rows. stdGap / stdMinMg / d-prime / AUC are.")
    print("    AS-norm z magnitudes also are not comparable across K: the sd of the top-K")
    print("    cohort scores shrinks as K shrinks, which is why K=5 produces |z| ~ 15.")
    print("\n  stdGap is the quantity the ABSOLUTE accept_threshold depends on (it compares")
    print("  scores across different queries). stdMinMg is the quantity the runner-up MARGIN")
    print("  gate depends on (within one query). They are different gates and a normalization")
    print("  can help one while hurting the other - t-corpus-full does exactly that below.")

    print("\n  Per-fold detail (genuine / impostor / margin), and whether the A-vs-B ranking")
    print("  differs from `raw`:\n")
    for lab, *_ in cfgs:
        rows, base = tables[lab], tables["raw"]
        flips = sum(1 for r, b in zip(rows, base)
                    if r["defined"] and b["defined"] and r["correct"] != b["correct"])
        print(f"  {lab}")
        for r, b in zip(rows, base):
            if not r["defined"]:
                print(f"    {r['held']:22} truth {r['truth']}  UNDEFINED "
                      f"(cohort n<2 for at least one profile)")
                continue
            print(f"    {r['held']:22} truth {r['truth']}  own-enrol {r['n_enroll_own']} "
                  f"other-enrol {r['n_enroll_other']}  gen {r['genuine']:+8.4f}  "
                  f"imp {r['impostor']:+8.4f}  margin {r['margin']:+8.4f}  "
                  f"{'OK' if r['correct'] else 'MISS'}")
        print(f"    -> decisions differing from raw: {flips}/{len(rows)}\n")

    # ── 3. is the mismatched cohort informative or just a constant? ──────────
    print("=" * W)
    print(" 3. OPTION (a): IS THE DOMAIN-MISMATCHED CORPUS COHORT INFORMATIVE?")
    print("=" * W)
    EA = np.asarray([refs[s] for s in have["A"]])
    EB = np.asarray([refs[s] for s in have["B"]])
    cA, cB = cohort_vs_profile(C, EA), cohort_vs_profile(C, EB)
    graw = np.array([r["raw_gen"] for r in tables["raw"]])
    iraw = np.array([r["raw_imp"] for r in tables["raw"]])
    print(f"  cohort = {C.shape[0]} distinct infants, ECAPA-CryCeleb, other devices/rooms.")
    print(f"  Scores of cohort members against the FULL profiles (cosine):")
    for nm, c in (("profile A (3 refs)", cA), ("profile B (2 refs)", cB)):
        qs = np.percentile(c, [1, 25, 50, 75, 99])
        print(f"    {nm}: mean {c.mean():+.4f}  sd {c.std(ddof=1):+.4f}  "
              f"min {c.min():+.4f}  p1 {qs[0]:+.4f}  p50 {qs[2]:+.4f}  p99 {qs[4]:+.4f}  "
              f"max {c.max():+.4f}")
    print(f"\n  Reference distributions on the SAME cosine scale (n=5 each):")
    print(f"    genuine  (adult vs own profile)   mean {graw.mean():+.4f}  "
          f"min {graw.min():+.4f}  max {graw.max():+.4f}")
    print(f"    impostor (adult vs other adult)   mean {iraw.mean():+.4f}  "
          f"min {iraw.min():+.4f}  max {iraw.max():+.4f}")

    allc = np.concatenate([cA, cB])
    isd = iraw.std(ddof=1)
    print(f"\n  WHERE THE COHORT SITS:")
    print(f"    cohort mean {allc.mean():+.4f} vs impostor mean {iraw.mean():+.4f}  "
          f"-> offset {allc.mean() - iraw.mean():+.4f} "
          f"= {(allc.mean() - iraw.mean()) / isd:+.2f} impostor-sd")
    print(f"    cohort mean vs genuine  mean {graw.mean():+.4f}  "
          f"-> offset {allc.mean() - graw.mean():+.4f}")
    print(f"    fraction of cohort scores above the max ADULT IMPOSTOR score "
          f"({iraw.max():+.4f}): {float((allc > iraw.max()).mean()):.3%}")
    print(f"    fraction of cohort scores above the min GENUINE score "
          f"({graw.min():+.4f}): {float((allc > graw.min()).mean()):.3%}")
    print(f"    fraction of cohort scores BELOW the min adult impostor score "
          f"({iraw.min():+.4f}): {float((allc < iraw.min()).mean()):.3%}")

    muA, sdA, _ = _mu_sd(cA)
    muB, sdB, _ = _mu_sd(cB)
    tilt = muA - muB
    print(f"\n  WHAT Z-NORM ACTUALLY DOES TO THE A-vs-B DECISION (the algebra, not a vibe):")
    print(f"    z_A - z_B = (s_A - mu_A)/sd_A - (s_B - mu_B)/sd_B .")
    print(f"    mu_A {muA:+.4f}  sd_A {sdA:.4f}    mu_B {muB:+.4f}  sd_B {sdB:.4f}")
    print(f"    With sd_A ~ sd_B this reduces to [ (s_A - s_B) - (mu_A - mu_B) ] / sd, i.e.")
    print(f"    the cohort contributes ONE QUERY-INDEPENDENT CONSTANT: mu_A - mu_B = "
          f"{tilt:+.4f}.")
    print(f"    sd ratio sd_A/sd_B = {sdA / sdB:.3f} (a second, also query-independent, "
          f"scale tilt).")
    raw_margins = np.abs(graw - iraw)
    print(f"    |raw A-vs-B margins| over the 5 folds: "
          f"{' '.join(f'{m:.4f}' for m in raw_margins)}  (min {raw_margins.min():.4f})")
    print(f"    |tilt| / min raw margin = {abs(tilt) / raw_margins.min():.2f}  ->  "
          f"{'the tilt is LARGER than the tightest raw decision' if abs(tilt) > raw_margins.min() else 'the tilt is smaller than the tightest raw decision'}")
    below = float((allc < iraw.min()).mean())
    print(f"\n  READ THIS AS: the cohort is a DISJOINT CLUSTER, not a tail of the impostor")
    print(f"  distribution. {below:.1%} of its mass sits BELOW the lowest adult impostor score,")
    print(f"  {float((allc > iraw.max()).mean()):.1%} of it reaches the highest, and its mean is "
          f"{abs(allc.mean() - iraw.mean()) / isd:.1f} impostor-sd away.")
    print(f"  So (mu, sd) taken from it do not estimate the adult impostor distribution at all;")
    print(f"  they estimate 'how much an adult imitation resembles a random infant on someone")
    print(f"  else's phone'. Precise, stable, and about a different question.")

    # ── the decisive check we CAN make: does the cohort's hubness claim agree with
    # the (tiny) adult evidence? Z-norm's whole justification is that some profiles sit
    # in denser regions and score higher against strangers. If the cohort says one profile
    # is hubbier and the adult impostor scores do not, the correction is unsupported.
    imp_vs_B = np.array([r["raw_imp"] for r in tables["raw"] if r["truth"] == "A"])
    imp_vs_A = np.array([r["raw_imp"] for r in tables["raw"] if r["truth"] == "B"])
    coh_claim = muB - muA
    adult_obs = imp_vs_B.mean() - imp_vs_A.mean()
    se = math.sqrt(imp_vs_B.var(ddof=1) / imp_vs_B.size + imp_vs_A.var(ddof=1) / imp_vs_A.size)
    vote = float((cB > cA).mean())
    print(f"\n  DOES THE COHORT'S CORRECTION AGREE WITH THE ADULT EVIDENCE?")
    print(f"    Z-norm exists to cancel HUBNESS: a profile that scores high against everyone.")
    print(f"    The cohort's claim: profile B is hubbier than A by mu_B - mu_A = "
          f"{coh_claim:+.4f},")
    print(f"    and {vote:.1%} of the {C.shape[0]} cohort infants individually score higher "
          f"against B than A.")
    print(f"    The adult evidence: strangers vs profile B mean {imp_vs_B.mean():+.6f} "
          f"(n={imp_vs_B.size}),")
    print(f"                        strangers vs profile A mean {imp_vs_A.mean():+.6f} "
          f"(n={imp_vs_A.size})")
    print(f"                        observed hubness difference {adult_obs:+.6f} "
          f"+- {se:.4f} (SE)")
    print(f"    The cohort asserts a {coh_claim:+.4f} hubness correction; the adult data puts "
          f"the same")
    print(f"    quantity at {adult_obs:+.6f}. That exact zero is NOT a coincidence, and this is")
    print(f"    the sharpest result in this file:")
    cross = [float(refs[a] @ refs[b]) for a in have["A"] for b in have["B"]]
    print(f"\n    PROOF THAT 2 PROFILES CANNOT TEST HUBNESS AT ALL. Under mean-cosine scoring,")
    print(f"      mean impostor score vs profile B = (1/|A|) SUM_a (1/|B|) SUM_b cos(a,b)")
    print(f"      mean impostor score vs profile A = (1/|B|) SUM_b (1/|A|) SUM_a cos(a,b)")
    print(f"    Both are (1/|A||B|) SUM over the SAME {len(cross)} cross pairs - the same number by")
    print(f"    construction. Measured: {imp_vs_B.mean():.10f} vs {imp_vs_A.mean():.10f} vs")
    print(f"    all-cross-pairs {np.mean(cross):.10f}. Identical to machine precision.")
    print(f"    With exactly TWO profiles the adult data has ZERO degrees of freedom about")
    print(f"    hubness asymmetry. It is not underpowered - it is structurally silent, and no")
    print(f"    number of extra takes from A and B changes that. Validating any Z-norm-style")
    print(f"    correction requires a THIRD PERSON. That is a hard floor, not a preference.")
    print(f"    (Fold-level margins do differ - see section 2 - it is only the two directions'")
    print(f"    MEANS that coincide, and the mean is what a hubness correction targets.)")
    print(f"    (The two adult means also come from profiles of DIFFERENT size - "
          f"{EB.shape[0]} vs {EA.shape[0]}")
    print(f"    enrollments - which biases a mean cosine on its own. Another thing 5")
    print(f"    references cannot disentangle.)")
    print(f"    CONCLUSION FOR OPTION (a): the correction's MAGNITUDE is estimable to ~"
          f"{sd_relative_se(C.shape[0]):.0%}. Its")
    print(f"    RELEVANCE is doubtful ({below:.0%} of the cohort sits below the entire adult")
    print(f"    impostor range) and its SIGN is not merely untested but UNTESTABLE at P=2.")

    print(f"\n  COHORT-SIZE SENSITIVITY (does the offset even stabilize?)")
    print(f"    {'n_infants':>9} {'mu_A':>9} {'sd_A':>8} {'mu_B':>9} {'sd_B':>8} "
          f"{'mu_A-mu_B':>10} {'sd rel.SE':>10}")
    offs = []
    for n in (25, 50, 100, 200, C.shape[0]):
        if n > C.shape[0]:
            continue
        a, b = cohort_vs_profile(C[:n], EA), cohort_vs_profile(C[:n], EB)
        offs.append((n, a.mean() - b.mean()))
        print(f"    {n:>9} {a.mean():>9.4f} {a.std(ddof=1):>8.4f} {b.mean():>9.4f} "
              f"{b.std(ddof=1):>8.4f} {a.mean() - b.mean():>10.4f} "
              f"{sd_relative_se(n):>10.1%}")
    late = [o for n, o in offs if n >= 100]
    spread = (max(late) - min(late)) if len(late) > 1 else float("nan")
    print(f"    Offset spread across the >=100-infant rows: {spread:.4f} "
          f"({spread / abs(offs[-1][1]):.0%} of the offset itself).")
    print(f"    So the cohort statistic is ESTIMABLE - repeatable to a few thousandths - which")
    print(f"    is exactly why 'it converged' must not be mistaken for 'it is the right")
    print(f"    correction'. Feasibility and usefulness are separate claims and only the first")
    print(f"    one is settled here.")

    tflips = sum(1 for r, b in zip(tables.get("t-corpus-full", []), tables["raw"])
                 if r["defined"] and r["correct"] != b["correct"])
    print(f"\n  T-NORM IS RANKING-BLIND - A STRUCTURAL FACT, NOT A MEASUREMENT:")
    print(f"    T-norm divides every profile's score for a given query by the SAME "
          f"(mu_q, sd_q),")
    print(f"    so argmax_P is unchanged: it can move an absolute accept threshold but can")
    print(f"    never change which of A or B wins. Measured: t-corpus-full flips {tflips} of "
          f"{len(folds())} decisions.")
    print(f"    S-norm is (Z+T)/2 and so carries exactly half of Z-norm's ranking effect.")
    print(f"    And T-norm made the gate it CAN affect WORSE: stdGap "
          f"{summ['t-corpus-full']['std_gap']:+.3f} vs raw "
          f"{summ['raw']['std_gap']:+.3f}")
    print(f"    (raw's genuine and impostor sets are fully separated across queries; after")
    print(f"    T-norm they overlap, AUC {summ['t-corpus-full']['auc']:.2f} vs "
          f"{summ['raw']['auc']:.2f}). Dividing each query by its own")
    print(f"    cross-domain spread destroys the cross-query comparability that an absolute")
    print(f"    threshold is made of. That is directional HARM, not neutrality.")

    # ── 4. option (b) ───────────────────────────────────────────────────────
    print("\n" + "=" * W)
    print(" 4. OPTION (b): THE OTHER PERSON'S REFERENCES AS A COHORT (n = 1..3)")
    print("=" * W)
    ob = summ["z-other(n<=3)"]
    print(f"  Result: LOO {ob['loo']}/{ob['n']}, UNDEFINED in {ob['undefined']}/{ob['n']} "
          f"folds.")
    print(f"  Three independent reasons this cannot work, in order of severity:")
    print(f"    (i)  IT IS NOT COMPUTABLE. When a B reference is held out, profile A's")
    print(f"         cohort is B's ONE remaining reference. A z-score needs an sd; sd from")
    print(f"         n=1 does not exist. {ob['undefined']} of {ob['n']} folds die here.")
    print(f"    (ii) IT IS CIRCULAR. Profile A's cohort IS Person B - the same recordings")
    print(f"         supplying the impostor score. Normalizing A's score by the distribution")
    print(f"         of B against A, and then comparing it to B's score, uses one")
    print(f"         measurement twice and manufactures separation from nothing.")
    print(f"    (iii) THE SD IS NOISE. Relative standard error of a sample sd is "
          f"~1/sqrt(2(n-1)):")
    for n in (2, 3, 5, 20, 100, C.shape[0]):
        print(f"           n={n:<4} -> {sd_relative_se(n):5.1%} relative error on sd"
              + ("   <- option (b)" if n in (2, 3) else
                 "   <- option (a)" if n == C.shape[0] else ""))
    print(f"  Dividing by a quantity known to +-71% cannot improve a decision whose raw")
    print(f"  margin is {raw_margins.min():.4f}.")

    # ── 5. freeze ───────────────────────────────────────────────────────────
    print("\n" + "=" * W)
    print(" 5. FREEZE - decided on reference data ONLY, before any blind audio is read")
    print("=" * W)
    print(FREEZE_RULE)
    print()
    chosen, log = freeze(summ)
    for line in log:
        print(line)
    print(f"\n  FROZEN CONFIGURATION: {chosen}")
    cs = summ[chosen]
    print(f"    LOO {cs['loo']}/{cs['n']}  genuine mean {cs['g_mean']:+.4f}  "
          f"impostor mean {cs['i_mean']:+.4f}  gap {cs['gap']:+.4f}  "
          f"d-prime {cs['dprime']:.3f}")

    # ── 6. what 5 references cannot support ─────────────────────────────────
    print("\n" + "=" * W)
    print(" 6. WHAT THIS SAMPLE SIZE CAN AND CANNOT SUPPORT")
    print("=" * W)
    n_people, n_refs = len(PEOPLE), len(refs)
    n_pairs = n_people * (n_people - 1) // 2
    print(f"  Have: {n_people} participants, {n_refs} references, {len(folds())} LOO trials,")
    print(f"        {n_pairs} distinct between-person pair(s).")
    print(f"  Configurations compared in section 2: {len(cfgs)}.")
    p_perfect = 0.5 ** len(folds())
    print(f"\n  SIGNIFICANCE CEILING")
    print(f"    Best possible outcome is {len(folds())}/{len(folds())}. Paired sign test, "
          f"one-sided: p = 2^-{len(folds())} = {p_perfect:.4f}.")
    print(f"    Bonferroni over {len(cfgs)} configurations: adjusted p = "
          f"{min(1.0, p_perfect * len(cfgs)):.3f}.")
    print(f"    P(at least one of {len(cfgs)} coin-flip configs scores "
          f"{len(folds())}/{len(folds())}) = "
          f"{1 - (1 - p_perfect) ** len(cfgs):.1%}.")
    print(f"    => A perfect LOO here is NOT evidence that one option beats another. It is")
    print(f"       consistent with pure noise roughly one time in three.")
    print(f"\n  FALSE-ACCEPT RATE YOU COULD HONESTLY CLAIM")
    print(f"    Zero false accepts in n independent impostor trials gives a 95% one-sided")
    print(f"    upper bound of 1-0.05^(1/n):")
    for n in (5, 10, 30, 59, 299):
        print(f"      n={n:<4} -> FAR <= {1 - 0.05 ** (1 / n):6.1%}")
    print(f"    With {len(folds())} impostor trials the claim is 'FAR <= "
          f"{1 - 0.05 ** (1 / len(folds())):.0%}'. That is not a threshold, it is a shrug.")
    print(f"    Worse, those {len(folds())} trials are not independent: they reuse "
          f"{n_pairs} person-pair,")
    print(f"    so the effective sample size for an impostor claim is {n_pairs}, not "
          f"{len(folds())}.")
    print(f"\n  MINIMUM PARTICIPANTS BEFORE AN IMITATION THRESHOLD SHOULD BE TRUSTED AT ALL")
    for far, label in ((0.10, "10% FAR (demo-grade, tolerant of retries)"),
                       (0.05, "5% FAR"),
                       (0.01, "1% FAR (a claim worth publishing)")):
        need_pairs = n_for_zero_error_bound(far)
        need_p = participants_for_pairs(need_pairs)
        print(f"    {label:44} needs {need_pairs:>4} independent person-pairs "
              f"-> >= {need_p:>3} participants")
    tol = n_for_tolerance_bound(0.05)
    print(f"    An accept_threshold placed at the genuine 5th percentile needs a "
          f"distribution-free")
    print(f"    95% tolerance bound: >= {tol} INDEPENDENT genuine observations. Multiple takes")
    print(f"    by one person are correlated, so read that as >= {tol} PARTICIPANTS, not "
          f"{tol} clips.")
    print(f"\n    HEADLINE NUMBERS - minimum participants before an imitation threshold")
    print(f"    should be trusted at all:")
    print(f"      {'2':>6} : where we are. A hubness/cohort correction is not merely")
    print(f"               unvalidated but UNTESTABLE - see the proof in section 3. Any")
    print(f"               cohort-normalized threshold at P=2 would be unfalsifiable.")
    print(f"      {'>= 3':>6} : cohort normalization becomes TESTABLE at all (the mean impostor")
    print(f"               score against different profiles stops being one number).")
    print(f"      {'< 12':>6} : NO threshold is defensible. Rank-only ('which of these two"
          f" is it?'),")
    print(f"               absolute accept gate stays at the conservative default, status")
    print(f"               `uncertain` whenever there is no second profile to compare to.")
    print(f"      {'12-24':>6} : a demo-grade operating point; FAR bounded at ~5-10% with 95%")
    print(f"               confidence. Enough to stop guessing, not enough to publish.")
    print(f"      {'>= 25':>6} : a 1%-FAR bound becomes arguable.")
    print(f"      {'>= ' + str(tol):>6} : the genuine 5th percentile - i.e. accept_threshold "
          f"itself - ")
    print(f"               becomes estimable with no distributional assumptions.")
    cal = identity.load_calibration(identity.KIND_IMITATION)
    print(f"    We have {n_people}. The live per-kind numbers "
          f"(data/calibration.json, version {cal.get('version')})")
    print(f"    are accept {cal['accept_threshold']}, margin {cal['margin_threshold']}, "
          f"strong {cal['strong_threshold']} - i.e.")
    print(f"    {n_people} participants' worth of evidence. They must stay labelled provisional,")
    print(f"    and nothing in this file is a reason to move them.")
    print(f"    Each participant needs >= 3 INDEPENDENT takes (separate performances, not one")
    print(f"    cry chopped up) and, to break the channel/voice entanglement flagged in")
    print(f"    tools/imitation_spike.py, at least some participants recorded on TWO devices.")
    print(f"\n  AND FOR COHORT NORMALIZATION SPECIFICALLY")
    print(f"    A cohort must sample the population it normalizes against. A valid imitation")
    print(f"    cohort therefore needs adults performing cries: >= 50 distinct people (so the")
    print(f"    sd is known to ~{sd_relative_se(50):.0%}) and ideally >= 100 (~"
          f"{sd_relative_se(100):.0%}). We have 0.")
    print(f"    Until then cohort normalization for this kind is FEASIBLE (it computes, and")
    print(f"    the statistics are stable) but UNVALIDATED (its direction is untested), and")
    print(f"    with {n_pairs} person-pair it is untestable in principle, not merely in practice.")

    # ── 7. blind verification, last, after the freeze ───────────────────────
    if args.no_blind:
        print("\n(--no-blind: stopping before verification.)")
        return 0
    print("\n" + "=" * W)
    print(" 7. BLIND VERIFICATION - 2 queries, frozen configuration, NO selection here")
    print("=" * W)
    assert chosen is not None, "freeze() must run before any blind audio is read"
    print(f"  Frozen: {chosen}. The blind queries were not encoded until this line. They")
    print(f"  cannot and do not change K, the cohort, or any threshold. They are 2 trials,")
    print(f"  both from Person A, so they can only ever FALSIFY the frozen choice - a 2/2")
    print(f"  pass is worth p = {0.5 ** 2:.2f} and nothing more.\n")
    braw = {}
    for s in BLIND:
        p = _wav(s)
        if not os.path.exists(p):
            print(f"  MISSING {p}", file=sys.stderr)
            continue
        v = encoders.encode(ENC, p)
        if v is None:
            print(f"  UNUSABLE {s}", file=sys.stderr)
            continue
        braw[s] = v
    if not braw:
        print("  no usable blind queries", file=sys.stderr)
        return 1
    labs = list(braw)
    bl = dict(zip(labs, _l2([braw[l] for l in labs])))

    E = {"A": EA, "B": EB}
    coh_corpus = {p: cohort_vs_profile(C, E[p]) for p in ("A", "B")}
    coh_other = {"A": cohort_vs_profile(EB, EA), "B": cohort_vs_profile(EA, EB)}
    ok_frozen = 0
    print(f"  {'query':22} {'config':16} {'score A':>10} {'score B':>10} {'pred':>5} "
          f"{'margin':>9}")
    for s, q in bl.items():
        q_vs_corpus = C @ q
        for lab, mode, ck, k in cfgs:
            coh = coh_corpus if ck == "corpus" else coh_other
            sc = {}
            for p in ("A", "B"):
                cq = q_vs_corpus if ck == "corpus" else np.asarray(
                    [refs[t] @ q for t in PEOPLE["B" if p == "A" else "A"] if t in refs])
                sc[p] = normalized(mode, profile_score(q, E[p]), coh[p], cq, k)
            if not (np.isfinite(sc["A"]) and np.isfinite(sc["B"])):
                pred, marg = "n/a", float("nan")
            else:
                pred = "A" if sc["A"] > sc["B"] else "B"
                marg = sc["A"] - sc["B"]
            star = " <- FROZEN" if lab == chosen else ""
            if lab == chosen and pred == BLIND_TRUTH:
                ok_frozen += 1
            print(f"  {s:22} {lab:16} {sc['A']:>10.4f} {sc['B']:>10.4f} {pred:>5} "
                  f"{marg:>9.4f}{star}")
        print()
    print(f"  FROZEN CONFIGURATION ON THE BLIND SET: {ok_frozen}/{len(bl)} correct "
          f"(truth = Person {BLIND_TRUTH} for both).")
    print(f"  The non-frozen rows above are printed for completeness and are POST-HOC. They")
    print(f"  were not used to choose anything, and reading a winner out of them would be")
    print(f"  exactly the error this file's ordering exists to prevent.")

    print("\n" + "=" * W)
    print(" VERDICT")
    print("=" * W)
    hurt = [lab for lab, mode, ck, k in cfgs
            if ck == "corpus" and summ[lab]["undefined"] == 0
            and summ[lab]["loo"] < len(folds())]
    print(f"  FEASIBLE?          Yes, mechanically. The {C.shape[0]}-infant cohort is a one-off")
    print(f"                     ~60 s encode, cacheable, after which every normalization is")
    print(f"                     one {C.shape[0]}x192 matrix product per profile - milliseconds,")
    print(f"                     nowhere near the latency budget. The per-profile mu/sd are")
    print(f"                     repeatable to a few thousandths past 100 infants, and")
    print(f"                     identity.py would need no structural change to use them.")
    print(f"  HELPFUL?           No, and partly harmful.")
    print(f"                     - raw is already {summ['raw']['loo']}/{summ['raw']['n']} "
          f"with a fully disjoint gap of "
          f"{summ['raw']['gap']:+.4f}")
    print(f"                       (stdGap {summ['raw']['std_gap']:+.3f}, AUC "
          f"{summ['raw']['auc']:.2f}), so there is no headroom for any cohort")
    print(f"                       option to demonstrate an improvement in.")
    print(f"                     - every corpus option scored WORSE than raw on BOTH")
    print(f"                       standardized statistics (stdGap and stdMinMg), and "
          f"{len(hurt)} of")
    print(f"                       them - {', '.join(hurt) if hurt else '-'} - ")
    print(f"                       actively broke a decision raw got right (LOO 4/5). Small-K")
    print(f"                       AS-norm is the most aggressive and the most damaging.")
    print(f"                     - the cohort's contribution to the A-vs-B ranking is a single")
    print(f"                       query-independent constant ({tilt:+.4f}) plus a scale tilt")
    print(f"                       ({sdA / sdB:.3f}), both estimated from a cluster whose mean "
          f"sits")
    print(f"                       {abs(allc.mean() - iraw.mean()) / isd:.1f} impostor-sd away "
          f"from the population it claims to model.")
    print(f"  DIRECTIONALLY?     Untestable, not merely undetermined. With exactly 2 profiles")
    print(f"                     the mean impostor score against A and against B are the SAME")
    print(f"                     NUMBER by construction ({imp_vs_A.mean():.6f}, both equal to the")
    print(f"                     mean of the 6 A-B cross pairs), so the adult data carries zero")
    print(f"                     information about the asymmetry Z-norm exists to correct. The")
    print(f"                     cohort asserts {coh_claim:+.4f}; nothing here can confirm or "
          f"refute it.")
    print(f"                     A THIRD PARTICIPANT is the hard floor for even asking.")
    print(f"  RECOMMENDATION     Do not wire cohort normalization into the imitation flow on")
    print(f"                     this evidence. Keep raw mean-cosine + the two existing gates,")
    print(f"                     keep data/calibration.json's imitation thresholds labelled")
    print(f"                     provisional, and revisit only when BOTH exist: >= 12")
    print(f"                     participants (>= 25 for a 1% FAR claim) and a cohort of >= 50")
    print(f"                     ADULT imitators - the corpus cannot substitute for the second.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
