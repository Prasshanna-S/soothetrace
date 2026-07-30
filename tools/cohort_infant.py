"""Cohort normalization (AS-norm) for SINGLE-PROFILE infant verification.

THE PROBLEM THIS EXISTS TO SOLVE
--------------------------------
`identity._evaluate` refuses every single-profile claim. With one enrolled profile there is
no runner-up, so the margin gate cannot fire and the ABSOLUTE threshold decides alone. That
threshold was measured at 93.3% true-accept / 6.7% FALSE-accept (data/calibration.json) - 
a stranger accepted roughly 1 in 15. On stage that reads as "second person is told they are
the first person", so the claim is refused instead.

THE METHOD
----------
Adaptive symmetric normalization (AS-norm), standard in speaker verification. A raw cosine
is not comparable across queries because some recordings are simply "close to everything"
(loud, broadband, average-sounding cries). Normalizing against an IMPOSTOR COHORT converts
the raw score into "how many cohort-standard-deviations above the crowd is this?", which is
per-query self-calibrating and therefore does not need a fixed absolute cosine bar.

    s_raw    = mean_i cos(q, e_i)                       over the profile's enrollments e_i
    cs_q     = cos(q, c) for every cohort embedding c    -> top-K highest (ADAPTIVE)
    z_q      = (s_raw - mean(top-K cs_q)) / (std + eps)
    cs_E     = mean_i cos(e_i, c) for every cohort c     -> top-K highest   (symmetric term,
               mirrors s_raw: mean over enrollments first, then adapt)
    z_e      = (s_raw - mean(top-K cs_E)) / (std + eps)
    s_as     = 0.5 * (z_q + z_e)

Decisions are taken on s_as, never on s_raw.

HARD RULES OBSERVED
-------------------
* mfcc87 ONLY (the infant encoder). Every vector - query, enrollment, cohort - is z-scored
  against the SAME population baseline and then L2'd, via `encoders.prepare`. No raw-cosine
  mfcc87 anywhere, no cross-encoder comparison anywhere.
* COHORT AND TEST IMPOSTORS ARE DISJOINT BY UUID. The corpus filename prefix is a 36-char
  device UUID; same UUID = same infant. UUIDs are split once, deterministically, into a
  cohort half and a test-impostor half. Reusing a cohort file as a test impostor would let
  the normalizer see the trial it is being scored on and would invalidate the FAR.
* NOTHING in here touches data/audio/replay_master (the blind queries) or the imitation
  domain. Selection happens on reference infant + corpus data only.

WHY THE FAR IS REPORTED THREE WAYS
---------------------------------
mfcc87 is channel-sensitive (docs/FINDINGS.md, tools/channel_robustness.py). The corpus was
recorded on hundreds of other phones; the live infants X and Y share ONE fixed rig. So a
corpus impostor is an easy reject for partly the wrong reason (channel), while a
different-infant-same-rig impostor is the genuinely hard case and the only one that matches
the live demo. Every table therefore reports:

    ALL      = same-rig impostors + corpus impostors   (the headline number)
    SAME-RIG = infant Y against profile X, and X against Y   (the HARD, honest number)
    CORPUS   = held-out corpus infants only             (cross-channel, easy)

The verdict is taken on SAME-RIG. Quoting the ALL number as the safety figure would be
self-flattery.

RESULT AS MEASURED - THE ANSWER IS NO
-------------------------------------
seed 0, cohort 299 embeddings / 147 corpus UUIDs, K=20, 15 genuine + 112 same-rig + 900
corpus impostor trials, leave-one-out, one profile enrolled at a time:

                          SAME-RIG impostors (decisive)          CORPUS impostors
    system              EER  TAR@FAR<=5%  FAR@TAR=100%        EER   separated?
    raw mean-cosine    6.90%     60.0%       39.3%           0.00%     YES
    AS-norm K=20       6.90%      0.0%        7.1%           0.00%     YES

Read the two halves:

* CROSS-CHANNEL STRANGERS WERE NEVER THE PROBLEM. Raw cosine already separates the held-out
  corpus infants perfectly (genuine min +0.7242 vs corpus max +0.4443, EER 0.00%). AS-norm
  cannot improve on a ceiling. ⚠️ So the pooled ALL-impostor EER (5.51% raw -> 0.40%
  AS-norm) is NOT a safety win: 89% of those trials are these free rejects and pooling them
  dilutes the hard set. An earlier draft of this tool quoted that number and it inverted the
  conclusion.
* ON THE DECISIVE SET - a different infant on the SAME rig - AS-norm is not an improvement.
  EER is identical (6.90% both). The curves CROSS: AS-norm is better only in the TAR=100%
  corner (FAR 7.1% vs 39.3%), while raw is better everywhere useful (TAR 60.0% vs 0.0% at
  FAR<=5%). The top same-rig impostor still outscores EVERY genuine trial under AS-norm, so
  no threshold separates them and FAR<=5% is unreachable at any usable TAR.

WHY, and this is the finding worth keeping: a cohort can only normalize an axis it spans.
mfcc87 is channel-sensitive and the corpus cohort is a different channel, so it lands near
-6.4 sigma while same-rig impostors (+6.3) sit right beside genuine trials (+9.0). The cohort
is far from BOTH, subtracts a nearly common offset along the same-rig confusion axis, and
carries almost no information about it. The implied fix is a SAME-RIG cohort (unenrolled
infants recorded on the demo rig). That is NOT measurable in this repo: only 2 live infants
exist, and putting Y in the cohort while testing Y as an impostor is the exact leakage this
file is built to avoid.

Also measured: the AS-norm threshold is cohort-relative, not portable. Re-drawing the cohort
over 5 splits moves thr@TAR=100% across +6.32 .. +9.56 and FAR(same-rig)@TAR=100% across
7.1% .. 19.6%, while the same-rig EER stays pinned at 6.90%. Rates generalize; thresholds
must be frozen together with the exact cohort embedding list.

USAGE
    cd /path/to/interaction-memory && . .venv/bin/activate
    python tools/cohort_infant.py                      # full grid + stability
    python tools/cohort_infant.py --cache /tmp/emb.npz # cache embeddings between runs
    python tools/cohort_infant.py --one-per-uuid       # cohort = 1 clip per infant
"""
from __future__ import annotations

import argparse
import glob
import os
import re
import sys
import time
from collections import defaultdict

import numpy as np

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "src"))

import config      # noqa: E402
import encoders    # noqa: E402
import store       # noqa: E402

ENC = encoders.MFCC87                      # infant domain. Never anything else in this file.
EPS = 1e-9

RIG_DIR = os.path.join(config.AUDIO_DIR, "round2_h")
CORPUS = os.path.join(_ROOT, "experiments", "donateacry-corpus",
                      "donateacry_corpus_cleaned_and_updated_data")

# Live rig, one fixed capture path. 06-Y3 is unusable (-38 dB) and is excluded by name.
INFANT_X = ["01-X1", "03-X2", "05-X3", "07-X4", "09-X5", "11-X6", "13-X7", "15-X8"]
INFANT_Y = ["02-Y1", "04-Y2", "08-Y4", "10-Y5", "12-Y6", "14-Y7", "16-Y8"]
UNUSABLE = ["06-Y3"]

UUID_RE = re.compile(r"^(.{36})")


# ───────────────────────────── loading / encoding ────────────────────────────

def _baseline():
    b = store.get_baseline(config.POPULATION_KEY)
    if not b or not b.get("mu") or not b.get("sd"):
        raise SystemExit("no population baseline - run tools/build_baseline.py first")
    return (np.asarray(b["mu"], dtype=np.float64),
            np.asarray(b["sd"], dtype=np.float64), int(b.get("n") or 0))


def _corpus_uuid(path: str) -> str:
    """Device UUID = first 36 chars of the basename. Case-folded: the corpus stores the
    same UUID in both cases across files, and treating those as two infants would split one
    infant across the cohort/test boundary - exactly the leak this file forbids."""
    m = UUID_RE.match(os.path.basename(path))
    return (m.group(1) if m else os.path.basename(path)).casefold()


def _encode_all(paths, cache=None):
    """path -> raw 87-d fingerprint. Files that fail to encode are dropped and reported."""
    cached = {}
    if cache and os.path.exists(cache):
        z = np.load(cache, allow_pickle=True)
        cached = {str(k): np.asarray(v, dtype=np.float64)
                  for k, v in zip(z["paths"], z["vecs"])}
    out, failed, t0 = {}, [], time.time()
    for i, p in enumerate(paths):
        if p in cached:
            out[p] = cached[p]
            continue
        v = encoders.encode(ENC, p)
        if v is None:
            failed.append(p)
        else:
            out[p] = np.asarray(v, dtype=np.float64)
        if (i + 1) % 100 == 0:
            print(f"    ...encoded {i + 1}/{len(paths)}", file=sys.stderr)
    if cache and out:
        np.savez_compressed(cache, paths=np.array(list(out)),
                            vecs=np.asarray(list(out.values())))
    return out, failed, time.time() - t0


# ───────────────────────────────── metrics ───────────────────────────────────

def _pct(x, p=1):
    return "--" if x is None else f"{100 * x:.{p}f}%"


def _num(x, p=4):
    return "--" if x is None else f"{x:+.{p}f}"


def _far(imp, t):
    return float(np.mean(imp >= t)) if len(imp) else 0.0


def _tar(gen, t):
    return float(np.mean(gen >= t)) if len(gen) else 0.0


def _candidates(gen, imp):
    """Thresholds to sweep: midpoints between every adjacent observed score, plus fences."""
    s = np.unique(np.concatenate([gen, imp]))
    mids = (s[:-1] + s[1:]) / 2.0 if len(s) > 1 else s
    return np.concatenate([[s[0] - 1e-6], np.atleast_1d(mids), [s[-1] + 1e-6]])


def _metrics(gen, imp):
    """EER + operating points. Returns plain floats; thresholds are on the SAME scale as the
    scores handed in (raw cosine or normalized z - never mixed)."""
    gen, imp = np.asarray(gen, dtype=np.float64), np.asarray(imp, dtype=np.float64)
    ts = _candidates(gen, imp)
    fars = np.array([_far(imp, t) for t in ts])
    tars = np.array([_tar(gen, t) for t in ts])
    frrs = 1.0 - tars

    j = int(np.argmin(np.abs(fars - frrs)))
    out = {
        "n_gen": len(gen), "n_imp": len(imp),
        "gen_mean": float(gen.mean()), "gen_min": float(gen.min()), "gen_max": float(gen.max()),
        "gen_sd": float(gen.std()),
        "imp_mean": float(imp.mean()), "imp_min": float(imp.min()), "imp_max": float(imp.max()),
        "imp_sd": float(imp.std()),
        "separated": bool(gen.min() > imp.max()),
        "gap": float(gen.min() - imp.max()),
        "eer": float((fars[j] + frrs[j]) / 2.0), "eer_thr": float(ts[j]),
    }
    for tgt in (0.0, 0.01, 0.05):
        ok = np.where(fars <= tgt + 1e-12)[0]
        if len(ok):
            # lowest threshold that still respects the FAR budget = highest TAR there
            i = int(ok[np.argmax(tars[ok])])
            out[f"tar@far{tgt}"] = float(tars[i])
            out[f"thr@far{tgt}"] = float(ts[i])
            out[f"far@far{tgt}"] = float(fars[i])
        else:
            out[f"tar@far{tgt}"] = None
            out[f"thr@far{tgt}"] = None
            out[f"far@far{tgt}"] = None
    # threshold that keeps every genuine trial, and what it costs in FAR
    keep_all = np.where(tars >= 1.0 - 1e-12)[0]
    if len(keep_all):
        i = int(keep_all[np.argmin(fars[keep_all])])
        out["thr@tar100"] = float(ts[i])
        out["far@tar100"] = float(fars[i])
    else:
        out["thr@tar100"] = out["far@tar100"] = None
    return out


# ───────────────────────── split + leave-one-out scoring ─────────────────────

def _split_and_score(vecs, mu, sd, rig, by_uuid, uuids, k_spec, n_test_want, seed,
                     one_per_uuid, verbose=False):
    """One deterministic cohort/test split, then the whole leave-one-out trial set.

    Returns every trial as a row carrying the raw score AND the normalized score for every
    K, so the systems are all scored on IDENTICAL trials - a per-system re-split would let
    a lucky split masquerade as a better normalizer.
    """
    rng = np.random.default_rng(seed)
    order = list(uuids)
    rng.shuffle(order)
    n_test = min(n_test_want, len(order) - 20)
    test_uuids, cohort_uuids = order[:n_test], order[n_test:]
    assert not (set(test_uuids) & set(cohort_uuids)), "cohort/test UUID leak"

    # one recording per test UUID -> every test impostor is a DIFFERENT infant
    test_files = [sorted(by_uuid[u])[0] for u in test_uuids]
    cohort_files = ([sorted(by_uuid[u])[0] for u in cohort_uuids] if one_per_uuid
                    else [p for u in cohort_uuids for p in sorted(by_uuid[u])])
    assert not (set(cohort_files) & set(test_files)), "cohort/test FILE leak"

    def P(paths):
        return encoders.prepare(ENC, [vecs[p] for p in paths], (mu, sd))

    C = P(cohort_files)                                    # (n_cohort, 87)
    RIG = {n: P([rig[n]])[0] for n in rig}
    TEST = dict(zip(test_files, P(test_files)))

    ks = []
    for tok in str(k_spec).split(","):
        tok = tok.strip().lower()
        ks.append(len(C) if tok in ("all", "full") else min(int(tok), len(C)))
    ks = sorted(set(ks))

    if verbose:
        print(f"\nsplit (seed={seed}, deterministic)")
        print(f"  COHORT        : {len(cohort_files)} embeddings from {len(cohort_uuids)} "
              f"UUIDs{' (1 per UUID)' if one_per_uuid else ' (all recordings per UUID)'}")
        print(f"  TEST IMPOSTORS: {len(test_files)} recordings from {len(test_files)} "
              f"DISTINCT UUIDs, none in the cohort")
        print(f"  disjointness  : asserted by UUID and by filename")
        print(f"  K values      : {ks}  (K={len(C)} == all)")

    # Each fold enrolls exactly ONE profile, so no runner-up ever exists - precisely the
    # situation identity.py refuses today. Genuine = the held-out file of that profile.
    # Impostors = every file of the OTHER live infant (same rig, HARD) + the held-out corpus
    # infants (cross-channel, easy).
    profiles = {"X": INFANT_X, "Y": INFANT_Y}
    rows = []
    t0 = time.time()
    n_scorings = 0
    for pname, files in profiles.items():
        other = INFANT_Y if pname == "X" else INFANT_X
        for held in files:
            enroll = [n for n in files if n != held]
            E = np.stack([RIG[n] for n in enroll])          # (n_enroll, 87)
            # Symmetric (enrollment-side) cohort statistic: mean over enrollments FIRST,
            # so it describes the same quantity s_raw does.
            cs_E = (C @ E.T).mean(axis=1)
            n_scorings += 1
            eside = {}
            for K in ks:
                top = np.sort(cs_E)[-K:]
                eside[K] = (float(top.mean()), float(top.std()))

            trials = [(held, 1, "genuine", RIG[held])]
            trials += [(n, 0, "same_rig", RIG[n]) for n in other]
            trials += [(os.path.basename(p), 0, "corpus", TEST[p]) for p in test_files]

            for tname, label, src, q in trials:
                s_raw = float(np.mean(E @ q))
                cs_q = C @ q
                n_scorings += 1
                row = {"profile": pname, "held_out": held, "n_enroll": len(enroll),
                       "trial": tname, "label": label, "source": src, "raw": s_raw}
                for K in ks:
                    top = np.sort(cs_q)[-K:]
                    z_q = (s_raw - top.mean()) / (top.std() + EPS)
                    mE, sE = eside[K]
                    z_e = (s_raw - mE) / (sE + EPS)
                    row[f"zq{K}"] = float(z_q)
                    row[f"as{K}"] = float(0.5 * (z_q + z_e))
                rows.append(row)

    if verbose:
        n_gen = sum(r["label"] == 1 for r in rows)
        n_sr = sum(r["source"] == "same_rig" for r in rows)
        n_co = sum(r["source"] == "corpus" for r in rows)
        print(f"\ntrials             : {len(rows)} total = {n_gen} genuine + {n_sr} same-rig "
              f"impostor + {n_co} corpus impostor")
        print(f"  folds            : {len(INFANT_X)} (profile X, "
              f"{len(INFANT_X) - 1} enrollments each) + {len(INFANT_Y)} (profile Y, "
              f"{len(INFANT_Y) - 1} enrollments each) = "
              f"{len(INFANT_X) + len(INFANT_Y)}")
        print(f"  scoring runtime  : {time.time() - t0:.2f}s for {n_scorings} cohort "
              f"scorings ({1000 * (time.time() - t0) / max(n_scorings, 1):.2f} ms per query, "
              f"all K included)")
    return {"rows": rows, "ks": ks, "C": C, "cohort_files": cohort_files,
            "cohort_uuids": cohort_uuids, "test_files": test_files,
            "seconds": time.time() - t0}


def _selector(rows):
    def sel(field, label, source=None):
        return np.array([r[field] for r in rows if r["label"] == label
                         and (source is None or r["source"] == source)])
    return sel


# ─────────────────────────────── the experiment ──────────────────────────────

def run(args) -> int:
    t_start = time.time()
    mu, sd, base_n = _baseline()
    print("=" * 100)
    print("COHORT-NORMALIZED SINGLE-PROFILE VERIFICATION - INFANT DOMAIN")
    print("=" * 100)
    print(f"encoder            : {ENC}  (z-score vs population baseline n={base_n}, then L2)")
    print(f"population baseline: {config.POPULATION_KEY}  dim={len(mu)}")

    # ---- inventory -----------------------------------------------------------
    rig = {n: os.path.join(RIG_DIR, n + ".wav") for n in INFANT_X + INFANT_Y}
    missing = [n for n, p in rig.items() if not os.path.exists(p)]
    if missing:
        print(f"missing rig audio: {missing}", file=sys.stderr)
        return 1
    corpus_files = sorted(glob.glob(os.path.join(CORPUS, "*", "*.wav")))
    if len(corpus_files) < 100:
        print(f"corpus too small at {CORPUS}", file=sys.stderr)
        return 1

    print(f"\nrig audio          : {len(INFANT_X)} X + {len(INFANT_Y)} Y "
          f"= {len(rig)} files (excluded {UNUSABLE} - unusable at -38 dB)")
    print(f"corpus files on disk: {len(corpus_files)}")

    # ---- encode --------------------------------------------------------------
    print("\nencoding (mfcc87) ...", file=sys.stderr)
    vecs, failed, t_enc = _encode_all([rig[n] for n in rig] + corpus_files, args.cache)
    print(f"encode             : {len(vecs)} usable, {len(failed)} unusable, "
          f"{t_enc:.1f}s")

    corpus_ok = [p for p in corpus_files if p in vecs]
    by_uuid = defaultdict(list)
    for p in corpus_ok:
        by_uuid[_corpus_uuid(p)].append(p)
    uuids = sorted(by_uuid)
    print(f"corpus usable      : {len(corpus_ok)} recordings across {len(uuids)} distinct "
          f"device UUIDs")

    # ---- one split + one full LOO pass ---------------------------------------
    tr = _split_and_score(vecs, mu, sd, rig, by_uuid, uuids, args.k,
                          args.n_test_impostors, args.seed, args.one_per_uuid, verbose=True)
    rows, ks, C = tr["rows"], tr["ks"], tr["C"]
    cohort_files, cohort_uuids, test_files = (tr["cohort_files"], tr["cohort_uuids"],
                                              tr["test_files"])

    # ---- score sets ---------------------------------------------------------
    sel = _selector(rows)

    systems = [("raw cosine (today)", "raw")]
    for K in ks:
        systems.append((f"z-norm query-only K={K}", f"zq{K}"))
    for K in ks:
        systems.append((f"AS-norm symmetric K={K}", f"as{K}"))

    IMP_SETS = [("ALL", None), ("SAME-RIG", "same_rig"), ("CORPUS", "corpus")]

    for iname, isrc in IMP_SETS:
        print("\n" + "=" * 100)
        print(f"IMPOSTOR SET: {iname}" + {
            None: "  (same-rig + corpus pooled - ⚠️ DILUTED, see below; not a safety number)",
            "same_rig": "  (infant Y vs profile X and X vs Y - the HARD case, one fixed rig)",
            "corpus": "  (held-out corpus infants - cross-channel, easy)"}[isrc])
        print("=" * 100)
        # FAR@TAR100 and TAR@FAR are the only SCALE-FREE columns here: a z-norm threshold at
        # K=20 lives on a different scale than one at K=100, so thresholds and gaps must
        # NEVER be compared between rows. Rate columns can be.
        hdr = (f"{'system':<26}{'gen mean':>9}{'gen min':>9}{'imp mean':>9}{'imp max':>9}"
               f"{'sep':>5}{'EER':>8}{'EERthr':>9}{'TAR@1%':>8}{'thr':>9}"
               f"{'TAR@5%':>8}{'thr':>9}{'FAR@TAR100':>11}{'thr':>9}")
        print(hdr)
        print("-" * len(hdr))
        for sname, field in systems:
            g, i = sel(field, 1), sel(field, 0, isrc)
            m = _metrics(g, i)
            print(f"{sname:<26}{m['gen_mean']:>9.4f}{m['gen_min']:>9.4f}"
                  f"{m['imp_mean']:>9.4f}{m['imp_max']:>9.4f}"
                  f"{('YES' if m['separated'] else 'no'):>5}"
                  f"{100 * m['eer']:>7.2f}%{m['eer_thr']:>9.4f}"
                  f"{_pct(m['tar@far0.01']):>8}{_num(m['thr@far0.01']):>9}"
                  f"{_pct(m['tar@far0.05']):>8}{_num(m['thr@far0.05']):>9}"
                  f"{_pct(m['far@tar100']):>11}{_num(m['thr@tar100']):>9}")

    # ---- detail on the decisive configuration -------------------------------
    print("\n" + "=" * 100)
    print("DETAIL - distributions per system (SAME-RIG impostors, the decisive set)")
    print("=" * 100)
    for sname, field in systems:
        g = sel(field, 1)
        i = sel(field, 0, "same_rig")
        c = sel(field, 0, "corpus")
        mg = _metrics(g, i)
        ma = _metrics(g, sel(field, 0, None))
        print(f"\n{sname}")
        print(f"  genuine  n={len(g):<4} mean {g.mean():+.4f}  sd {g.std():.4f}  "
              f"min {g.min():+.4f}  max {g.max():+.4f}")
        print(f"  same-rig n={len(i):<4} mean {i.mean():+.4f}  sd {i.std():.4f}  "
              f"min {i.min():+.4f}  max {i.max():+.4f}")
        print(f"  corpus   n={len(c):<4} mean {c.mean():+.4f}  sd {c.std():.4f}  "
              f"min {c.min():+.4f}  max {c.max():+.4f}")
        print(f"  same-rig separation gap (gen_min - imp_max) = {mg['gap']:+.4f}"
              f"  -> {'SEPARATED' if mg['separated'] else 'OVERLAP'}")
        print(f"  same-rig  EER {100 * mg['eer']:6.2f}% @ thr {mg['eer_thr']:+.4f}"
              f" | TAR@FAR=0% {_pct(mg['tar@far0.0']):>6} @ thr {_num(mg['thr@far0.0'])}"
              f" | thr keeping TAR=100% {_num(mg['thr@tar100'])} costs FAR "
              f"{_pct(mg['far@tar100'])}")
        print(f"  ALL       EER {100 * ma['eer']:6.2f}% @ thr {ma['eer_thr']:+.4f}"
              f" | TAR@FAR=0% {_pct(ma['tar@far0.0']):>6} @ thr {_num(ma['thr@far0.0'])}")

    # ---- cohort-split stability ---------------------------------------------
    # A hard-coded AS-norm threshold is only meaningful WITH the cohort it was measured on:
    # the score is expressed in cohort standard deviations, so a different cohort moves the
    # whole scale. Re-splitting shows how much. RATES should be stable, THRESHOLDS need not
    # be - and if the threshold wanders while the rates hold, the number a caller hard-codes
    # must be frozen together with the exact cohort file list.
    stab = _stability(vecs, mu, sd, rig, by_uuid, uuids, args)

    # ---- verdict -------------------------------------------------------------
    _verdict(rows, sel, systems, ks, len(C), len(cohort_uuids), len(test_files),
             args, time.time() - t_start, stab)
    return 0


def _stability(vecs, mu, sd, rig, by_uuid, uuids, args):
    """Repeat the whole experiment on other cohort/test splits. Reference data only."""
    print("\n" + "=" * 100)
    print(f"COHORT-SPLIT STABILITY - same experiment re-run on {args.stability_seeds} "
          f"further splits")
    print("=" * 100)
    hdr = (f"{'seed':>5}{'best AS K':>11}{'same-rig EER':>14}{'ALL EER':>9}"
           f"{'FAR-sr@TAR100':>15}{'thr@TAR100':>12}{'gen mean':>10}")
    print(hdr)
    print("-" * len(hdr))
    out = []
    for seed in range(args.seed, args.seed + max(args.stability_seeds, 0) + 1):
        tr = _split_and_score(vecs, mu, sd, rig, by_uuid, uuids, args.k,
                              args.n_test_impostors, seed, args.one_per_uuid)
        s = _selector(tr["rows"])
        best = None
        for K in tr["ks"]:
            m = _metrics(s(f"as{K}", 1), s(f"as{K}", 0, "same_rig"))
            ma = _metrics(s(f"as{K}", 1), s(f"as{K}", 0, None))
            far100 = m["far@tar100"] if m["far@tar100"] is not None else 1.0
            cand = (-m["eer"], -far100, -ma["eer"], K, m, ma)
            if best is None or cand[:3] > best[:3]:
                best = cand
        _, _, _, K, m, ma = best
        out.append({"seed": seed, "k": K, "eer_sr": m["eer"], "eer_all": ma["eer"],
                    "far100_sr": m["far@tar100"], "thr100": m["thr@tar100"],
                    "gen_mean": m["gen_mean"]})
        print(f"{seed:>5}{K:>11}{100 * m['eer']:>13.2f}%{100 * ma['eer']:>8.2f}%"
              f"{_pct(m['far@tar100']):>15}{_num(m['thr@tar100']):>12}"
              f"{m['gen_mean']:>10.3f}")
    if out:
        eers = np.array([o["eer_sr"] for o in out])
        alls = np.array([o["eer_all"] for o in out])
        thrs = np.array([o["thr100"] for o in out])
        print(f"\n  same-rig EER across splits : {100 * eers.min():.2f}% - "
              f"{100 * eers.max():.2f}%   (spread {100 * (eers.max() - eers.min()):.2f} pts)")
        print(f"  ALL EER across splits      : {100 * alls.min():.2f}% - "
              f"{100 * alls.max():.2f}%")
        print(f"  thr@TAR100 across splits   : {thrs.min():+.3f} - {thrs.max():+.3f}"
              f"   (spread {thrs.max() - thrs.min():.3f} in cohort sigmas)")
        print("  -> the RATES are what generalize. The THRESHOLD is cohort-relative and must"
              " be frozen")
        print("     together with the exact cohort embedding list that produced it.")
    return out


def _verdict(rows, sel, systems, ks, n_cohort, n_cohort_uuids, n_test, args, elapsed,
             stab=None):
    """Decide on SAME-RIG impostors - the only impostor set that matches the live situation
    (a different infant recorded through the identical capture path). Chosen on reference
    data only; nothing in this file ever reads data/audio/replay_master.

    ⚠️ RANKING IS SCALE-FREE ON PURPOSE. A z-norm score at K=20 and one at K=100 live on
    different scales, so "bigger separation gap" is meaningless across rows and an earlier
    version of this function got the answer wrong by ranking on it (it crowned K=all, whose
    EER is twice the best row's). Only RATES - EER, TAR at a FAR budget, FAR at TAR=100% - 
    may be compared between systems.
    """
    print("\n" + "=" * 100)
    print("VERDICT")
    print("=" * 100)

    def _m(field, source):
        return _metrics(sel(field, 1), sel(field, 0, source))

    as_fields = [(f"AS-norm symmetric K={K}", f"as{K}", K) for K in ks]
    ranked = []
    for sname, field, K in as_fields:
        m = _m(field, "same_rig")
        far100 = m["far@tar100"] if m["far@tar100"] is not None else 1.0
        ranked.append((-m["eer"], -far100, -_m(field, None)["eer"], sname, field, K, m))
    ranked.sort(reverse=True)
    _, _, _, best_name, best_field, best_k, best = ranked[0]

    raw_sr = _m("raw", "same_rig")
    raw_all = _m("raw", None)
    best_all = _m(best_field, None)
    best_co = _m(best_field, "corpus")

    n_pairs_sr = len({(r["profile"], r["trial"]) for r in rows if r["source"] == "same_rig"})
    n_pairs_co = len({(r["profile"], r["trial"]) for r in rows if r["source"] == "corpus"})

    # ---------------- baseline, restated on this trial set --------------------
    print("\n1. BASELINE - raw mean-cosine, single profile (what ships today)")
    print(f"   SAME-RIG impostors : EER {100 * raw_sr['eer']:.2f}%   "
          f"genuine min {raw_sr['gen_min']:+.4f} vs impostor max {raw_sr['imp_max']:+.4f}"
          f"  -> OVERLAP by {-raw_sr['gap']:.4f}")
    print(f"   ALL impostors      : EER {100 * raw_all['eer']:.2f}%")
    print(f"   at the shipped accept_threshold 0.7880 -> "
          f"TAR {100 * _tar(sel('raw', 1), 0.788):.1f}%, "
          f"FAR(same-rig) {100 * _far(sel('raw', 0, 'same_rig'), 0.788):.1f}%, "
          f"FAR(all) {100 * _far(sel('raw', 0, None), 0.788):.1f}%")
    print(f"   to accept ALL genuine it must drop to {_num(raw_sr['thr@tar100'])}, which "
          f"costs FAR(same-rig) {_pct(raw_sr['far@tar100'])}")

    # ---------------- best cohort-normalized system ---------------------------
    best_sep = ("SEPARATED" if best["separated"]
                else f"OVERLAP by {-best['gap']:.4f}")
    print(f"\n2. BEST COHORT-NORMALIZED SYSTEM (by same-rig EER, then FAR@TAR=100%): "
          f"{best_name}")
    print(f"   SAME-RIG impostors : EER {100 * best['eer']:.2f}%   "
          f"genuine min {best['gen_min']:+.4f} vs impostor max {best['imp_max']:+.4f}"
          f"  -> {best_sep}")
    print(f"   ALL impostors      : EER {100 * best_all['eer']:.2f}%   "
          f"(raw was {100 * raw_all['eer']:.2f}%)")
    print(f"   CORPUS impostors   : EER {100 * best_co['eer']:.2f}%  "
          f" - {'separated' if best_co['separated'] else 'overlapping'}")

    print(f"\n   threshold sweep on {best_name} (this is the table a caller reads):")
    print(f"   {'threshold':>10}{'TAR':>8}{'FAR same-rig':>14}{'FAR corpus':>12}"
          f"{'FAR all':>9}")
    g = sel(best_field, 1)
    isr, ico, iall = (sel(best_field, 0, "same_rig"), sel(best_field, 0, "corpus"),
                      sel(best_field, 0, None))
    for t in sorted({round(x, 3) for x in [best["thr@tar100"], best["eer_thr"],
                                           best["thr@far0.05"], best["thr@far0.01"],
                                           best["thr@far0.0"], g.min(), isr.max()]
                     if x is not None}):
        print(f"   {t:>+10.3f}{_pct(_tar(g, t)):>8}{_pct(_far(isr, t)):>14}"
              f"{_pct(_far(ico, t)):>12}{_pct(_far(iall, t)):>9}")

    # ---------------- the answer ---------------------------------------------
    separated = best["separated"]
    thr_safe = (round(best["imp_max"] + 0.5 * (best["gen_min"] - best["imp_max"]), 4)
                if separated else None)

    print("\n" + "-" * 100)
    print("ANSWER - does AS-norm make single-profile verification safe enough to re-enable?")
    print("-" * 100)

    if separated:
        print("\nYES, on this evidence. Genuine and same-rig-impostor scores SEPARATE with no")
        print("overlap, so a midpoint threshold false-accepted nothing at 100% true-accept.")
        print("\nEXACT NUMBERS TO HARD-CODE:")
        print(f'    method                       = "as_norm_symmetric"')
        print(f'    encoder                      = "{ENC}"')
        print(f'    cohort_top_k                 = {best_k}')
        print(f'    as_norm_accept_threshold     = {thr_safe}')
        print(f'    measured_tar                 = 1.0000')
        print(f'    measured_far_same_rig        = {_far(isr, thr_safe):.4f}')
        print(f'    measured_far_all_impostors   = {_far(iall, thr_safe):.4f}')
        return _footer(best, best_all, n_pairs_sr, n_pairs_co, n_cohort, n_cohort_uuids,
                       n_test, args, elapsed, stab)

    raw_co = _m("raw", "corpus")
    print("\nNO. On the impostor set that decides the demo - a different infant on the SAME")
    print("rig - cohort normalization does not help at all, and at the low-FAR operating")
    print("points you would actually pick it is WORSE than the raw cosine it replaces.")
    print("identity.py's refusal of the single-profile claim should STAND as written.")

    print("\n   (a) CROSS-CHANNEL STRANGERS WERE NEVER THE PROBLEM - so there is no win here.")
    print(f"       raw cosine ALREADY separates the 60 held-out corpus infants perfectly: "
          f"EER {100 * raw_co['eer']:.2f}%,")
    print(f"       genuine min {raw_co['gen_min']:+.4f} vs corpus impostor max "
          f"{raw_co['imp_max']:+.4f}. AS-norm also scores "
          f"{100 * best_co['eer']:.2f}%.")
    print( "       Both are at the ceiling. This is the channel effect, not voice identity:")
    print( "       mfcc87 is channel-sensitive and the corpus is hundreds of other phones.")
    print(f"       ⚠️ THEREFORE the ALL-impostor column ({100 * raw_all['eer']:.2f}% raw -> "
          f"{100 * best_all['eer']:.2f}% AS-norm) is NOT a")
    print(f"       safety improvement - {100 * (1 - best['n_imp'] / best_all['n_imp']):.0f}% "
          f"of those trials are these free rejects, and pooling them")
    print( "       DILUTES the hard set. Do not quote it. An earlier draft of this tool did,")
    print( "       and it inverted the conclusion.")

    print("\n   (b) ON THE SAME-RIG SET, AS-NORM AND RAW ARE THE SAME OR RAW IS BETTER.")
    print(f"       EER: {100 * raw_sr['eer']:.2f}% (raw) vs {100 * best['eer']:.2f}% "
          f"({best_name}) - identical.")
    print( "       The two curves CROSS, so which is 'better' depends entirely on the")
    print( "       operating point, and at the safe end raw wins:")
    print(f"       {'operating point':<30}{'raw':>8}{best_name:>26}")
    for tgt in (0.01, 0.05):
        print(f"       {'TAR at FAR(same-rig)<=' + f'{100 * tgt:.0f}%':<30}"
              f"{_pct(raw_sr[f'tar@far{tgt}']):>8}{_pct(best[f'tar@far{tgt}']):>26}"
              f"   <- raw better")
    print(f"       {'FAR(same-rig) at TAR=100%':<30}{_pct(raw_sr['far@tar100']):>8}"
          f"{_pct(best['far@tar100']):>26}   <- AS-norm better")
    print( "       AS-norm only wins in the TAR=100% corner, i.e. it lifts the single worst")
    print( "       genuine trial off the floor; it does NOT pull the worst impostors down.")
    print(f"       The top same-rig impostor still outscores EVERY genuine trial "
          f"({best['imp_max']:+.4f} >")
    print(f"       genuine max {best['gen_max']:+.4f}), which is why TAR at FAR<=5% is "
          f"{_pct(best['tar@far0.05'])}.")

    print("\n   (c) WHY - the finding worth keeping. Cohort normalization can only calibrate")
    print( "       directions the COHORT actually covers. The corpus cohort is a different")
    print(f"       channel, so it lands at {best_co['imp_mean']:+.2f} sigma while same-rig "
          f"impostors sit at {best['imp_mean']:+.2f} and")
    print(f"       genuine at {best['gen_mean']:+.2f}. The cohort is far from BOTH, so it "
          f"subtracts a nearly common")
    print( "       offset along the same-rig confusion axis and carries almost no")
    print( "       information about it. A cohort cannot normalize an axis it does not span.")

    print("\n   BEST AVAILABLE SINGLE-PROFILE OPERATING POINT, IF YOU SHIP IT ANYWAY")
    print(f"   ({best_name}, its TAR=100% corner - the one place it beats raw. The numbers")
    print("   below are the honest best case, NOT a recommendation to enable the claim):")
    print("\n   EXACT NUMBERS TO HARD-CODE:")
    print(f'    method                       = "as_norm_symmetric"')
    print(f'    encoder                      = "{ENC}"')
    print(f'    cohort_top_k                 = {best_k}')
    print(f'    cohort_size                  = {n_cohort}   # embeddings, {n_cohort_uuids} '
          f'distinct corpus UUIDs')
    print(f'    as_norm_accept_threshold     = {best["thr@tar100"]:+.4f}   '
          f'# keeps TAR = 100%')
    print(f'      -> measured TAR              = {100 * _tar(g, best["thr@tar100"]):.1f}%')
    print(f'      -> FAR, different infant SAME RIG = '
          f'{100 * _far(isr, best["thr@tar100"]):.1f}%   <-- the number that decides safety')
    print(f'      -> FAR, unenrolled corpus infant  = '
          f'{100 * _far(ico, best["thr@tar100"]):.1f}%')
    print(f'      -> FAR, all impostors             = '
          f'{100 * _far(iall, best["thr@tar100"]):.1f}%')
    print(f'    as_norm_strict_threshold     = {best["eer_thr"]:+.4f}   # EER point, '
          f'TAR {100 * _tar(g, best["eer_thr"]):.1f}% / FAR(same-rig) '
          f'{100 * _far(isr, best["eer_thr"]):.1f}%')
    for tgt in (0.0, 0.01, 0.05):
        thr = best[f"thr@far{tgt}"]
        if thr is None:
            print(f'    FAR(same-rig) <= {100 * tgt:>4.1f}%          = unreachable on this data')
        else:
            print(f'    FAR(same-rig) <= {100 * tgt:>4.1f}%          -> threshold {thr:+.4f}, '
                  f'TAR {100 * _tar(g, thr):.1f}%')
    # Head-to-head at MATCHED same-rig FAR. Comparing "AS-norm at its best threshold" to
    # "raw at its shipped threshold" would be comparing two different operating points and
    # would flatter whichever one happened to sit lower; matched-FAR is the honest form.
    as_thr = best["thr@tar100"]
    as_far = _far(isr, as_thr)
    raw_isr = sel("raw", 0, "same_rig")
    raw_g = sel("raw", 1)
    raw_thr_matched = None
    for t in np.sort(np.unique(np.concatenate([raw_g, raw_isr])))[::-1]:
        if _far(raw_isr, t) <= as_far + 1e-12:
            raw_thr_matched = float(t)
    print("\n   HEAD-TO-HEAD AT MATCHED SAME-RIG FAR (the only fair comparison):")
    print(f"     at FAR(same-rig) = {_pct(as_far)} - "
          f"AS-norm K=20 thr {as_thr:+.4f} -> TAR {_pct(_tar(g, as_thr))} "
          f"({round(_tar(g, as_thr) * best['n_gen'])}/{best['n_gen']} genuine)")
    if raw_thr_matched is not None:
        print(f"     at FAR(same-rig) = {_pct(_far(raw_isr, raw_thr_matched))} - "
              f"raw      thr {raw_thr_matched:+.4f} -> TAR "
              f"{_pct(_tar(raw_g, raw_thr_matched))} "
              f"({round(_tar(raw_g, raw_thr_matched) * best['n_gen'])}/{best['n_gen']} genuine)")
        d = round((_tar(g, as_thr) - _tar(raw_g, raw_thr_matched)) * best["n_gen"])
        print(f"     -> difference on the same-rig task: {d:+d} genuine trial(s) out of "
              f"{best['n_gen']}. At n={best['n_gen']} that is")
        print(f"        NOT a significant improvement. On the same-rig axis AS-norm is a "
              f"wash, not a fix.")
    if stab:
        f100 = [o["far100_sr"] for o in stab if o["far100_sr"] is not None]
        t100 = [o["thr100"] for o in stab if o["thr100"] is not None]
        if f100:
            print("\n   ⚠️ AND THAT OPERATING POINT IS ITSELF COHORT-DEPENDENT. Re-drawing the")
            print(f"   cohort over {len(stab)} splits moves FAR(same-rig)@TAR=100% across "
                  f"{_pct(min(f100))} - {_pct(max(f100))}")
            print(f"   and the threshold across {min(t100):+.3f} - {max(t100):+.3f}. So "
                  f"{_pct(best['far@tar100'])} is the LUCKY end of")
            print("   the range, not a stable figure - one more reason not to ship this as a "
                  "guarantee.")
    print("\n   READ THAT AS: a single-profile 'is it them?' at the TAR=100% threshold above")
    print(f"   still accepts a different infant on the same rig {_pct(as_far)} of the time - "
          f"about 1 in {max(1, round(1 / max(as_far, 1e-9)))}, i.e. the SAME order as the")
    print(f"   ~1-in-{max(1, round(1 / max(_far(raw_isr, 0.788), 1e-9)))} the shipped raw "
          f"threshold already gives. That is exactly the risk identity.py refuses,")
    print("   and cohort normalization does not remove it. There is no second risk that it")
    print("   removes instead: the cross-channel stranger was already handled by raw (a).")

    print("\n   WHAT WOULD ACTUALLY CLOSE IT (implied by the numbers above, NOT measured "
          "here):")
    print("     a SAME-RIG cohort - a handful of recordings from infants captured on the")
    print("     demo rig who are never enrolled. That puts cohort mass on the confusion axis")
    print("     the corpus cannot reach. It is unmeasurable with the data in this repo: only")
    print("     2 live infants exist, and using Y in the cohort while testing Y as an")
    print("     impostor is precisely the leakage this experiment is built to avoid.")
    return _footer(best, best_all, n_pairs_sr, n_pairs_co, n_cohort, n_cohort_uuids,
                   n_test, args, elapsed, stab)


def _footer(best, best_all, n_pairs_sr, n_pairs_co, n_cohort, n_cohort_uuids, n_test,
            args, elapsed, stab=None):
    print("\n" + "-" * 100)
    print("SAMPLE SIZE - READ BEFORE QUOTING ANY NUMBER ABOVE")
    print("-" * 100)
    print(f"  genuine trials      : {best['n_gen']} (leave-one-out over 8 X + 7 Y "
          f"recordings) from TWO infants on ONE rig.")
    print(f"  same-rig impostors  : {best['n_imp']} trials, but only {n_pairs_sr} distinct "
          f"(profile, impostor-file) pairs")
    print(f"                        re-scored across folds -> CORRELATED, not independent. "
          f"And only 2 impostor")
    print(f"                        IDENTITIES exist. A FAR estimated from 2 identities has "
          f"a very wide")
    print(f"                        confidence interval; the point estimate is not a "
          f"population FAR.")
    print(f"  corpus impostors    : {n_test} distinct identities ({n_pairs_co} pairs, "
          f"{best_all['n_imp'] - best['n_imp']} trials), 1 recording")
    print(f"                        each, cross-channel - an easier reject than the live "
          f"case, partly for")
    print(f"                        the wrong reason (channel, not voice).")
    print(f"  K was chosen from {len(args.k.split(','))} candidate values against "
          f"{best['n_gen']} genuine trials. That is thin: it can")
    print(f"                        rank K, it cannot resolve small differences between "
          f"adjacent K.")
    print(f"  blind queries       : untouched. Nothing here read data/audio/replay_master.")
    print(f"\nruntime {elapsed:.1f}s total | cohort {n_cohort} embeddings from "
          f"{n_cohort_uuids} UUIDs | split seed {args.seed}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--k", default="10,20,50,100,all",
                    help="adaptive top-K cohort sizes (comma separated; 'all' = whole cohort)")
    ap.add_argument("--n-test-impostors", type=int, default=60,
                    help="held-out corpus UUIDs used as TEST impostors (>=40 required)")
    ap.add_argument("--seed", type=int, default=0, help="split seed (deterministic)")
    ap.add_argument("--one-per-uuid", action="store_true",
                    help="cohort = 1 recording per UUID instead of all recordings")
    ap.add_argument("--stability-seeds", type=int, default=4,
                    help="extra cohort/test splits to re-run for the stability table")
    ap.add_argument("--cache", default=None,
                    help="optional .npz embedding cache path (outside the repo)")
    args = ap.parse_args()
    if args.n_test_impostors < 40:
        print("--n-test-impostors must be >= 40", file=sys.stderr)
        return 1
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
