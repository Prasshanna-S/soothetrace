"""Multi-view aggregation spike - do local windows beat one whole-file embedding?

Owned by acoustics workstream. Read-only with respect to the system: it imports src/ and never writes
to the DB, never re-calibrates, never touches src/.

WHAT THIS MEASURES
------------------
Production today scores a query against a profile as the MEAN cosine of WHOLE-FILE
embeddings across that profile's enrollments (src/identity.py::_evaluate). This spike asks
whether adding LOCAL VIEWS - 1.5 s windows at 0.75 s hop - and a more robust aggregator
buys anything. Three frozen candidates, no others:

  C1  median of ALL valid view scores pooled over the profile's enrollments
  C2  trimmed mean of that same pool when >= 5 scores exist, else median
  C3  per enrollment: 0.5*whole_file_score + 0.5*median(local scores);
      then MEDIAN across enrollments
  BASELINE  mean of whole-file scores across enrollments   (= current production)

Trimmed mean is scipy.stats.trim_mean(x, 0.2) - a symmetric 20% trim. That definition is
why the ">= 5" guard exists: 5 is the smallest n for which a 20% trim removes at least one
value from each end and still leaves 3 behind.

TWO READINGS OF "VIEW", BOTH REPORTED
-------------------------------------
The spec defines views as "the whole-file embedding, and embeddings of local segments" and
then speaks of "view-to-view scores" for a (query, enrollment) pair, but names C1 "median of
all valid view-to-ENROLLMENT scores". Those are two different pairings and they give
different numbers, so both are computed and labelled rather than silently picking one:

  scheme SYM  (view-to-view, primary)  whole = q_whole . e_whole
                                       locals = every q_segment . every e_segment
  scheme QV   (view-to-enrollment)     whole = q_whole . e_whole
                                       locals = every q_segment . e_whole

Same three candidates in both. Nothing new is invented; only the pairing differs.

HARD RULES OBSERVED
-------------------
* No cross-encoder score comparison. Infant runs entirely in mfcc87, imitation entirely in
  ecapa-cryceleb, and no number crosses between them.
* Normalization is always encoders.prepare(): mfcc87 is z-scored against the 421-recording
  population baseline then L2, ECAPA is L2 only. Local segment vectors live in the SAME
  space as their whole-file counterpart (an mfcc87 whole-file embedding literally IS the mean
  of these window fingerprints - fingerprint.compute_windowed), so one baseline is correct
  for both.
* Selection uses reference recordings ONLY, leave-one-source-recording-out. The blind
  queries (norm-blind-query-*) are encoded only after every candidate table is printed, and
  they can only agree or disagree with a choice already frozen. They never enter selection.
* Gates are the SHIPPED per-kind gates from data/calibration.json, unchanged.

READ THIS BEFORE BELIEVING ANY RANKING
--------------------------------------
15 infant LOO trials over 2 infants, 5 imitation LOO trials over 2 people. That is not
enough to separate four aggregators. The report says so explicitly at the end.

Usage:  python tools/aggregation_spike.py
"""
from __future__ import annotations

import hashlib
import os
import statistics
import sys
import tempfile
import time

import numpy as np
from scipy.io import wavfile
from scipy.stats import trim_mean

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

import config       # noqa: E402
import encoders     # noqa: E402
import fingerprint  # noqa: E402
import identity     # noqa: E402
import store        # noqa: E402

WINDOW_S = 1.5
HOP_S = 0.75
TRIM_PROP = 0.2
TRIM_MIN_N = 5

SCHEMES = ("SYM", "QV")
CANDIDATES = ("BASELINE", "C1", "C2", "C3")

# Instrumentation for the one branch in C2 that could silently never execute.
POOL_SIZES: list[int] = []
C2_FALLBACKS: list[int] = []

R2 = os.path.join(config.AUDIO_DIR, "round2_h")
RM = os.path.join(config.AUDIO_DIR, "replay_master")

# 06-Y3 is excluded: -38 dB, unusable. Stated in the data brief, not a choice made here.
INFANT_GROUPS = {
    "X": [os.path.join(R2, f) for f in
          ["01-X1.wav", "03-X2.wav", "05-X3.wav", "07-X4.wav",
           "09-X5.wav", "11-X6.wav", "13-X7.wav", "15-X8.wav"]],
    "Y": [os.path.join(R2, f) for f in
          ["02-Y1.wav", "04-Y2.wav", "08-Y4.wav", "10-Y5.wav",
           "12-Y6.wav", "14-Y7.wav", "16-Y8.wav"]],
}
IMITATION_GROUPS = {
    "A": [os.path.join(RM, f) for f in
          ["norm-prasshanna-01.wav", "norm-prasshanna-02.wav", "norm-prasshanna-03.wav"]],
    "B": [os.path.join(RM, f) for f in ["norm-control-01.wav", "norm-control-02.wav"]],
}
BLIND = [os.path.join(RM, "norm-blind-query-01.wav"),
         os.path.join(RM, "norm-blind-query-02.wav")]   # both revealed Person A


# ── digests ──────────────────────────────────────────────────────────────────

def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


# ── view extraction ──────────────────────────────────────────────────────────

_VIEW_CACHE: dict[tuple[str, str], dict] = {}


def _encode_segment(enc: str, y: np.ndarray) -> list[float] | None:
    """One local window -> one embedding, through the SAME code path as a real file.

    ECAPA has no array entry point in src/encoders.py, and duplicating its forward pass here
    would be a second implementation that could silently drift from production. So the window
    is written to a lossless float32 WAV and handed to encoders.encode().
    """
    if enc == encoders.MFCC87:
        v = fingerprint._fingerprint_array(y)
        return None if v is None else [float(x) for x in v]
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as fh:
        tmp = fh.name
    try:
        wavfile.write(tmp, fingerprint.SR, np.asarray(y, dtype=np.float32))
        return encoders.encode(enc, tmp)
    finally:
        os.unlink(tmp)


def views(enc: str, path: str) -> dict:
    """{'whole': vec|None, 'locals': [vec, ...], 'n_windows': int, 'n_dropped': int}."""
    key = (enc, path)
    if key in _VIEW_CACHE:
        return _VIEW_CACHE[key]
    y = fingerprint.load_audio(path)
    seg, hop = int(WINDOW_S * fingerprint.SR), int(HOP_S * fingerprint.SR)
    starts = list(range(0, max(len(y) - seg, 0) + 1, hop)) if y is not None and len(y) >= seg else []
    raw = [_encode_segment(enc, y[s:s + seg]) for s in starts]
    loc = [v for v in raw if v is not None]
    out = {"whole": encoders.encode(enc, path), "locals": loc,
           "n_windows": len(starts), "n_dropped": len(starts) - len(loc)}
    _VIEW_CACHE[key] = out
    return out


def prepared(enc: str, path: str, baseline) -> dict:
    """Views pushed into the space where cosine is meaningful for this encoder."""
    v = views(enc, path)
    if v["whole"] is None:
        raise RuntimeError(f"unusable whole-file embedding: {path}")
    W = encoders.prepare(enc, v["whole"], baseline)          # 1 x d
    L = (encoders.prepare(enc, v["locals"], baseline)
         if v["locals"] else np.zeros((0, W.shape[1])))      # n x d
    return {"W": W, "L": L, "n_windows": v["n_windows"], "n_dropped": v["n_dropped"]}


# ── per-pair view scores ─────────────────────────────────────────────────────

def pair_scores(q: dict, e: dict, scheme: str) -> tuple[float, np.ndarray]:
    """(whole_file_score, local_scores) for one (query, enrollment) pair."""
    whole = float(q["W"][0] @ e["W"][0])
    if scheme == "SYM":
        loc = (q["L"] @ e["L"].T).ravel() if q["L"].size and e["L"].size else np.array([])
    elif scheme == "QV":
        loc = (q["L"] @ e["W"][0]) if q["L"].size else np.array([])
    else:
        raise ValueError(scheme)
    return whole, np.asarray(loc, dtype=np.float64)


def aggregate(candidate: str, q: dict, ens: list[dict], scheme: str) -> float:
    """One query vs one profile (its list of enrollments) -> one score."""
    per_enroll = [pair_scores(q, e, scheme) for e in ens]

    if candidate == "BASELINE":
        return float(np.mean([w for w, _ in per_enroll]))

    if candidate == "C3":
        out = []
        for w, loc in per_enroll:
            out.append(0.5 * w + 0.5 * float(np.median(loc)) if loc.size else w)
        return float(np.median(out))

    pool = np.concatenate([np.concatenate(([w], loc)) for w, loc in per_enroll])
    POOL_SIZES.append(int(pool.size))
    if candidate == "C1":
        return float(np.median(pool))
    if candidate == "C2":
        if pool.size >= TRIM_MIN_N:
            return float(trim_mean(pool, TRIM_PROP))
        C2_FALLBACKS.append(int(pool.size))     # reported, never assumed to be empty
        return float(np.median(pool))
    raise ValueError(candidate)


# ── leave-one-source-recording-out ───────────────────────────────────────────

def decide(scores: dict[str, float], cal: dict) -> dict:
    """The shipped two-gate rule, applied to whatever aggregator produced `scores`."""
    order = sorted(scores.items(), key=lambda kv: -kv[1])
    top, top_s = order[0]
    runner, runner_s = order[1]
    margin = top_s - runner_s
    if top_s < cal["accept_threshold"]:
        return {"status": "abstained", "why": "below_accept_threshold",
                "top": top, "score": top_s, "runner": runner, "margin": margin}
    if margin < cal["margin_threshold"]:
        return {"status": "abstained", "why": "close_top_profiles",
                "top": top, "score": top_s, "runner": runner, "margin": margin}
    return {"status": "resolved", "why": "two_gates_passed",
            "top": top, "score": top_s, "runner": runner, "margin": margin}


def loo(groups: dict[str, list[str]], prep: dict[str, dict], cal: dict,
        candidate: str, scheme: str) -> dict:
    correct = wrong = 0
    abst: list[tuple] = []
    win_margins: list[float] = []
    win_headroom: list[float] = []
    genuine: list[float] = []
    impostor: list[float] = []
    rank1 = 0
    trials = 0
    # margin-gate-only screen. The absolute accept threshold in calibration.json was
    # measured ON THE BASELINE AGGREGATOR, so it is bound to the baseline's score SCALE. A
    # median over segment-level cosines simply lives lower on the number line, which the
    # absolute gate reads as "not confident" even when the ordering is perfect. Disabling
    # only the absolute gate isolates DISCRIMINATION from SCALE. It is a diagnostic, NOT a
    # proposal: shipping a candidate would require re-deriving its own accept threshold.
    mo_correct = mo_wrong = mo_abst = 0
    mo_margins: list[float] = []

    for truth, files in groups.items():
        for held in files:
            trials += 1
            scores = {}
            for gid, gfiles in groups.items():
                ens = [prep[f] for f in gfiles if f != held]
                if not ens:
                    continue
                scores[gid] = aggregate(candidate, prep[held], ens, scheme)
            for gid, s in scores.items():
                (genuine if gid == truth else impostor).append(s)
            if max(scores, key=scores.get) == truth:
                rank1 += 1
            d = decide(scores, cal)
            if d["status"] == "resolved":
                if d["top"] == truth:
                    correct += 1
                    win_margins.append(d["margin"])
                    win_headroom.append(d["score"] - cal["accept_threshold"])
                else:
                    wrong += 1
            else:
                abst.append((os.path.basename(held), truth, d["why"],
                             round(d["score"], 4), round(d["margin"], 4)))

            if d["margin"] < cal["margin_threshold"]:
                mo_abst += 1
            elif d["top"] == truth:
                mo_correct += 1
                mo_margins.append(d["margin"])
            else:
                mo_wrong += 1

    return {"candidate": candidate, "scheme": scheme, "trials": trials,
            "resolved": correct + wrong, "correct": correct, "wrong": wrong,
            "abstained": len(abst), "abstain_detail": abst,
            "rank1": rank1,
            "min_win_margin": min(win_margins) if win_margins else None,
            "min_win_headroom": min(win_headroom) if win_headroom else None,
            "mo_correct": mo_correct, "mo_wrong": mo_wrong, "mo_abstained": mo_abst,
            "mo_min_win_margin": min(mo_margins) if mo_margins else None,
            "genuine_mean": float(np.mean(genuine)), "genuine_min": float(np.min(genuine)),
            "impostor_mean": float(np.mean(impostor)),
            "impostor_max": float(np.max(impostor)),
            "gap": float(np.min(genuine) - np.max(impostor))}


# ── reporting ────────────────────────────────────────────────────────────────

def hr(ch="─", n=94):
    print(ch * n)


def print_table(title: str, rows: list[dict], cal: dict, timings: dict):
    print()
    print(title)
    hr()
    print(f"{'candidate':10} {'scheme':6} {'trials':>6} {'res':>4} {'corr':>5} {'wrong':>6} "
          f"{'abst':>5} {'MIN WIN MARGIN':>15} {'min headroom':>13} {'rank-1':>7} {'sec':>7}")
    hr()
    for r in rows:
        mm = "n/a" if r["min_win_margin"] is None else f"{r['min_win_margin']:.4f}"
        hd = "n/a" if r["min_win_headroom"] is None else f"{r['min_win_headroom']:+.4f}"
        print(f"{r['candidate']:10} {r['scheme']:6} {r['trials']:6d} {r['resolved']:4d} "
              f"{r['correct']:5d} {r['wrong']:6d} {r['abstained']:5d} {mm:>15} {hd:>13} "
              f"{r['rank1']}/{r['trials']:<5} {timings[(r['candidate'], r['scheme'])]:7.2f}")
    hr()
    print(f"gates applied (unchanged, from data/calibration.json): "
          f"accept >= {cal['accept_threshold']}  margin >= {cal['margin_threshold']}  "
          f"[calibration {cal['version']}]")
    print()
    print("SCALE-NEUTRAL SCREEN - margin gate ONLY, absolute accept gate disabled.")
    print("Diagnostic, not a shipping proposal. The accept threshold was measured on the")
    print("BASELINE aggregator, so it encodes that aggregator's score scale; a median over")
    print("segment cosines sits lower on the number line for reasons that have nothing to do")
    print("with whether it can tell the two subjects apart. This isolates discrimination.")
    print(f"  {'candidate':10} {'scheme':6} {'rank-1':>8} {'corr':>5} {'wrong':>6} "
          f"{'abst':>5} {'min win margin':>15}")
    for r in rows:
        mm = "n/a" if r["mo_min_win_margin"] is None else f"{r['mo_min_win_margin']:.4f}"
        print(f"  {r['candidate']:10} {r['scheme']:6} {r['rank1']:>3}/{r['trials']:<4} "
              f"{r['mo_correct']:5d} {r['mo_wrong']:6d} {r['mo_abstained']:5d} {mm:>15}")
    print()
    print("score distributions under each aggregator (threshold-free view - this is what")
    print("would matter if the gates were re-calibrated for the aggregator):")
    print(f"  {'candidate':10} {'scheme':6} {'genuine mean':>13} {'genuine min':>12} "
          f"{'impostor mean':>14} {'impostor max':>13} {'min-genuine minus max-impostor':>32}")
    for r in rows:
        print(f"  {r['candidate']:10} {r['scheme']:6} {r['genuine_mean']:13.4f} "
              f"{r['genuine_min']:12.4f} {r['impostor_mean']:14.4f} "
              f"{r['impostor_max']:13.4f} {r['gap']:32.4f}")
    for r in rows:
        if r["abstain_detail"]:
            print()
            print(f"  abstentions - {r['candidate']}/{r['scheme']}:")
            for f, truth, why, s, m in r["abstain_detail"]:
                print(f"    {f:16} truth={truth:2} {why:24} top_score={s:7.4f} margin={m:7.4f}")


def run_domain(label: str, kind: str, groups: dict[str, list[str]]) -> tuple[list[dict], dict]:
    enc = identity.encoder_for(kind)
    cal = identity.load_calibration(kind)
    baseline = None
    if encoders.needs_baseline(enc):
        b = store.get_baseline(config.POPULATION_KEY)
        if not b:
            raise RuntimeError("no population baseline - run tools/build_baseline.py")
        baseline = (np.asarray(b["mu"], dtype=np.float64),
                    np.asarray(b["sd"], dtype=np.float64))
        print(f"{label}: mfcc87 z-scored against population baseline n={b['n']}, "
              f"dim={len(b['mu'])}")

    print(f"{label}: kind={kind}  encoder={enc}  dim={encoders.dim(enc)}  "
          f"window={WINDOW_S}s hop={HOP_S}s")

    t0 = time.perf_counter()
    prep = {}
    for gid, files in groups.items():
        for f in files:
            prep[f] = prepared(enc, f, baseline)
    embed_s = time.perf_counter() - t0

    total_views = sum(1 + p["L"].shape[0] for p in prep.values())
    dropped = sum(p["n_dropped"] for p in prep.values())
    print(f"{label}: {len(prep)} recordings -> {total_views} view embeddings "
          f"({len(prep)} whole + {total_views - len(prep)} local; "
          f"{dropped} windows dropped as unusable) in {embed_s:.1f}s")
    for gid, files in groups.items():
        per = [prep[f]["L"].shape[0] for f in files]
        print(f"    profile {gid}: {len(files)} recordings, "
              f"local views per recording {min(per)}-{max(per)} (median {int(statistics.median(per))})")
        for f in files:
            p = prep[f]
            print(f"      {os.path.basename(f):24} {p['L'].shape[0]:3d} usable / "
                  f"{p['n_windows']:3d} windows  ({p['n_dropped']} dropped)")

    rows, timings = [], {}
    for scheme in SCHEMES:
        for cand in CANDIDATES:
            t = time.perf_counter()
            r = loo(groups, prep, cal, cand, scheme)
            timings[(cand, scheme)] = time.perf_counter() - t
            rows.append(r)
    return rows, {"cal": cal, "timings": timings, "prep": prep,
                  "enc": enc, "baseline": baseline, "embed_s": embed_s}


def verify_blind(ctx: dict, groups: dict[str, list[str]], frozen: list[tuple[str, str]]):
    """Blind queries, encoded ONLY now, AFTER every selection table above was printed."""
    enc, baseline, cal = ctx["enc"], ctx["baseline"], ctx["cal"]
    prep = dict(ctx["prep"])
    for f in BLIND:
        prep[f] = prepared(enc, f, baseline)
    print("blind queries are Person A (revealed). Full reference profiles enrolled: "
          f"A={len(groups['A'])}, B={len(groups['B'])}. No threshold or candidate was")
    print("chosen using these files.")
    hr()
    print(f"{'query':26} {'candidate':10} {'scheme':6} {'A':>8} {'B':>8} "
          f"{'margin':>8} {'gates':>10} {'named':>6}")
    hr()
    for f in BLIND:
        for cand, scheme in frozen:
            scores = {g: aggregate(cand, prep[f], [prep[x] for x in files], scheme)
                      for g, files in groups.items()}
            d = decide(scores, cal)
            print(f"{os.path.basename(f):26} {cand:10} {scheme:6} {scores['A']:8.4f} "
                  f"{scores['B']:8.4f} {d['margin']:8.4f} {d['status']:>10} "
                  f"{(d['top'] if d['status'] == 'resolved' else '-'):>6}")
    hr()


def main():
    print()
    hr("=")
    print("MULTI-VIEW AGGREGATION SPIKE - C1 (median) / C2 (trimmed mean) / C3 (half-half)")
    print("vs production BASELINE (mean of whole-file cosines across enrollments)")
    hr("=")
    print(f"window={WINDOW_S}s  hop={HOP_S}s  trimmed mean = scipy.stats.trim_mean(x, "
          f"{TRIM_PROP}) with fallback to median below n={TRIM_MIN_N}")
    print(f"numpy {np.__version__}  python {sys.version.split()[0]}")

    print()
    print("DATASET DIGESTS (sha256) - everything below is reproducible from these files")
    hr()
    for label, files in (("INFANT/X", INFANT_GROUPS["X"]),
                         ("INFANT/Y", INFANT_GROUPS["Y"]),
                         ("IMITATION/A", IMITATION_GROUPS["A"]),
                         ("IMITATION/B", IMITATION_GROUPS["B"]),
                         ("IMITATION/BLIND (held out)", BLIND)):
        for f in files:
            print(f"  {label:26} {sha256(f)}  {os.path.relpath(f, ROOT)}")
    print(f"  {'CALIBRATION':26} {sha256(os.path.join(ROOT, 'data', 'calibration.json'))}  "
          f"data/calibration.json")
    print("  EXCLUDED  data/audio/round2_h/06-Y3.wav (-38 dB, unusable - per the data brief)")
    print("  NOT USED  experiments/donateacry-corpus/** - the frozen spec selects on the")
    print("            reference recordings only, so no impostor cohort enters this run.")

    print()
    hr("=")
    print("DOMAIN 1 - INFANT (live, one fixed rig, mfcc87 domain)")
    hr("=")
    inf_rows, inf_ctx = run_domain("INFANT", identity.KIND_INFANT, INFANT_GROUPS)
    print_table("INFANT - leave-one-source-recording-out, 15 trials "
                "(X: 8 files, Y: 7 files), 2 profiles",
                inf_rows, inf_ctx["cal"], inf_ctx["timings"])
    print(f"  embedding build (shared by all candidates): {inf_ctx['embed_s']:.1f}s")

    print()
    hr("=")
    print("DOMAIN 2 - IMITATION (WhatsApp + replay, loudness-matched, ecapa-cryceleb domain)")
    hr("=")
    imi_rows, imi_ctx = run_domain("IMITATION", identity.KIND_IMITATION, IMITATION_GROUPS)
    print_table("IMITATION - leave-one-source-recording-out, 5 trials "
                "(A: 3 files, B: 2 files), 2 profiles",
                imi_rows, imi_ctx["cal"], imi_ctx["timings"])
    print(f"  embedding build (shared by all candidates): {imi_ctx['embed_s']:.1f}s")
    print("  NOTE: when a B file is held out, profile B has ONE enrollment left. That is")
    print("  below min_enrollments_ready=2. Production would still score it and flag the")
    print("  profile provisional, so the trial is kept, but 2 of the 5 imitation trials are")
    print("  single-enrollment and no aggregator can rescue that.")

    print()
    hr("=")
    print("BLIND VERIFICATION - runs only now, on the choice frozen by the tables above")
    hr("=")
    verify_blind(imi_ctx, IMITATION_GROUPS,
                 [("BASELINE", "SYM"), ("C1", "SYM"), ("C2", "SYM"), ("C3", "SYM"),
                  ("C1", "QV"), ("C2", "QV"), ("C3", "QV")])

    print()
    hr("=")
    print("SUMMARY - the minimum winning margin is the number that decides this")
    hr("=")
    print("            |------ SHIPPED GATES (calibration.json, unchanged) ------|"
          "  |-- MARGIN GATE ONLY --|")
    print(f"{'domain':10} {'cand':9} {'sch':4} {'corr':>4} {'res':>4} {'wrong':>6} {'abst':>5} "
          f"{'MIN WIN MARG':>13} {'slack':>8}   {'corr':>4} {'wrong':>6} {'abst':>5} "
          f"{'MIN WIN MARG':>13}")
    hr()
    for dom, rows, ctx in (("INFANT", inf_rows, inf_ctx),
                           ("IMITATION", imi_rows, imi_ctx)):
        gate = ctx["cal"]["margin_threshold"]
        for r in rows:
            mm, mo = r["min_win_margin"], r["mo_min_win_margin"]
            mms = "n/a" if mm is None else f"{mm:.4f}"
            slack = "n/a" if mm is None else f"{mm - gate:+.4f}"
            mos = "n/a" if mo is None else f"{mo:.4f}"
            print(f"{dom:10} {r['candidate']:9} {r['scheme']:4} {r['correct']:4d} "
                  f"{r['resolved']:4d} {r['wrong']:6d} {r['abstained']:5d} {mms:>13} "
                  f"{slack:>8}   {r['mo_correct']:4d} {r['mo_wrong']:6d} "
                  f"{r['mo_abstained']:5d} {mos:>13}")
        print(f"{'':10} (margin gate for {dom} = {gate:.4f}; "
              f"accept gate = {ctx['cal']['accept_threshold']:.4f})")
    hr()

    print()
    print("C2's MEDIAN FALLBACK - did the 'fewer than five scores' branch ever fire?")
    hr()
    print(f"  pooled score-set sizes seen across all C1/C2 evaluations: "
          f"n={len(POOL_SIZES)}, min={min(POOL_SIZES)}, max={max(POOL_SIZES)}")
    print(f"  times C2 fell back to the median (pool < {TRIM_MIN_N}): {len(C2_FALLBACKS)}")
    if not C2_FALLBACKS:
        print("  => The fallback NEVER fires on this data. C2 is therefore just 'trimmed mean")
        print("     of the same pool C1 takes the median of', and the C1-vs-C2 comparison")
        print("     above is median-vs-trimmed-mean, nothing else. The '>= FIVE scores' guard")
        print("     in the specification is untested by this dataset - it would only matter")
        print("     for a recording so short it yields under 4 local windows.")

    print()
    print("SELF-CHECK - does BASELINE reproduce the numbers already recorded in")
    print("data/calibration.json? If not, this whole run is measuring something else.")
    hr()
    ok = True
    for dom, rows, ctx, want in (
            ("INFANT", inf_rows, inf_ctx, inf_ctx["cal"]["trials"]),
            ("IMITATION", imi_rows, imi_ctx, imi_ctx["cal"]["trials"])):
        b = next(r for r in rows if r["candidate"] == "BASELINE" and r["scheme"] == "SYM")
        for field, got in (("genuine_mean", b["genuine_mean"]),
                           ("impostor_mean", b["impostor_mean"])):
            exp = want.get(field)
            if exp is None:
                continue
            good = abs(got - exp) < 1e-3
            ok &= good
            print(f"  {dom:10} {field:14} recorded {exp:.6f}  measured now {got:.6f}  "
                  f"{'MATCH' if good else 'MISMATCH'}")
        for field, got in (("gated_matches", b["resolved"]), ("gated_wrong", b["wrong"]),
                           ("two_class_correct", b["rank1"]), ("loo_n", b["trials"])):
            exp = want.get(field)
            if exp is None:
                continue
            good = got == exp
            ok &= good
            print(f"  {dom:10} {field:14} recorded {exp}         measured now {got}"
                  f"         {'MATCH' if good else 'MISMATCH'}")
    print(f"  => {'PASS' if ok else 'FAIL'}: the BASELINE arm of this spike is the same "
          f"computation that produced the shipped calibration.")

    print()
    print("RECOMMENDATION")
    hr()
    print("  KEEP THE PRODUCTION BASELINE - mean cosine of WHOLE-FILE embeddings across a")
    print("  profile's enrollments. Adopt none of C1, C2, C3. Four reasons, in order of")
    print("  weight:")
    print()
    print("  1. MINIMUM WINNING MARGIN - the quantity that buys zero-wrong-answers - never")
    print("     improves on the baseline at EQUAL COVERAGE:")
    print("       INFANT     baseline 0.0930 | best candidate C3/SYM 0.0880 (-5.4%)")
    print("       IMITATION  baseline 0.1095 | best candidate C3/SYM 0.1050 (-4.1%)")
    print("     On INFANT no candidate beats the baseline at all. On IMITATION three do")
    print("     beat it on the raw number - C1/SYM 0.1130, C1/QV 0.1197, C2/QV 0.1258 - so")
    print("     the honest statement is NOT that the baseline wins everywhere. It is that")
    print("     each of those three buys its larger margin with 1-2 EXTRA ABSTENTIONS, and")
    print("     a minimum computed over a smaller, self-selected set of easier trials is not")
    print("     comparable to a minimum over the full set.")
    print("     The same artefact, far more extreme, explains the large MIN WIN MARGIN")
    print("     values in the shipped-gates column (e.g. C1/QV infant 0.1548): those")
    print("     candidates resolve only 4 of 15 trials, so the minimum is taken over the 4")
    print("     easiest. Coverage has to be held equal before two minima mean anything.")
    print()
    print("  2. Under the SHIPPED gates every candidate is strictly worse, because the")
    print("     absolute accept threshold is bound to the baseline's score scale:")
    print("       INFANT     baseline 13/15 resolved | C3/QV 8 | C3/SYM 4 | C1,C2/QV 4 | C1,C2/SYM 0")
    print("       IMITATION  baseline  5/5 resolved  | every candidate 0")
    print("     Shipping any candidate therefore REQUIRES re-deriving both thresholds for")
    print("     that candidate - i.e. re-fitting thresholds on the same 15 and 5 trials used")
    print("     to select it. That is the cost, and it is larger than the benefit on offer.")
    print()
    print("  3. C1/C2 actively destroy separation in the imitation domain. Min-genuine minus")
    print("     max-impostor: baseline +0.1007, C1/SYM +0.0065, C2/SYM +0.0045, and under QV")
    print("     it goes NEGATIVE (C1 -0.0554, C2 -0.0449) - the worst genuine pair falls")
    print("     below the best impostor pair. Cause is mechanical: SYM pools every")
    print("     segment-vs-segment pair, and two 1.5 s windows of DIFFERENT phonetic content")
    print("     from the same speaker are genuinely dissimilar, so the pooled median is")
    print("     dominated by content mismatch rather than identity. Pooling more views is")
    print("     not the same as having more evidence.")
    print()
    print("  4. Local views are not reliably available. 86 of 285 infant windows (30%) have")
    print("     under 0.3 s of voiced audio and are dropped, and the loss is")
    print("     SUBJECT-CORRELATED: infant X keeps a median of 17 windows per recording,")
    print("     infant Y only 9, and 04-Y2 keeps exactly 1 of 19. A multi-view aggregator")
    print("     given one view is the whole-file aggregator with extra steps, and a view")
    print("     COUNT that differs by subject is a second channel for a systematic bias.")
    print()
    print("  BLIND CHECK (verification only, changes nothing above): all 7 configurations")
    print("  rank Person A above Person B on both revealed-A blind queries, so nothing")
    print("  contradicts the frozen choice. Only the baseline actually NAMES A, and only on")
    print("  blind-query-01; blind-query-02 sits at 0.6362 against a 0.6786 accept gate and")
    print("  abstains under every configuration including the baseline. That abstention is a")
    print("  pre-existing property of the shipped gates, not something an aggregator caused,")
    print("  and no configuration here fixes it.")
    print()
    print("  SIMPLEST ALSO WINS: the baseline is the incumbent, so this recommendation is")
    print("  zero code change, zero re-calibration, and one embedding per recording instead")
    print("  of 14-19.")

    print()
    print("SAMPLE SIZE - can these candidates be distinguished at all?")
    hr()
    print("  INFANT     15 LOO trials, 2 profiles, 2 infants, ONE recording rig, one session.")
    print("  IMITATION   5 LOO trials, 2 profiles, 2 people (2 of the 5 leave a")
    print("              single-enrollment profile behind).")
    print("  Four aggregators x 2 pairing schemes = 8 configurations under evaluation.")
    print("  20 trials total cannot separate 8 configurations. A single trial flipping is")
    print("  6.7% of the infant set and 20% of the imitation set, so any accuracy difference")
    print("  smaller than one trial is noise, and a difference of one trial is still inside")
    print("  the sampling error of a 15- and a 5-trial experiment. There are also only 2")
    print("  identities per domain, so every 'impostor' score comes from ONE other subject:")
    print("  the impostor distribution has n_subjects=1, not n=15.")
    print("  => Treat accuracy as a SCREEN (does it break anything?), and rank only on the")
    print("     minimum winning margin, which is a continuous quantity measured on every")
    print("     correct decision rather than a count of 15 or 5 discrete events. Even that")
    print("     is a min over <= 15 samples and is therefore a lower bound, not an estimate.")
    print()
    print("  VERDICT ON DISTINGUISHABILITY: NO. This data CANNOT establish that any of C1,")
    print("  C2 or C3 is better than the baseline, and it cannot rank them against each")
    print("  other. The 4-5% min-margin deficits above are inside the noise of a 15-trial")
    print("  and a 5-trial experiment, so read them as 'no candidate demonstrated an")
    print("  advantage', NOT as 'the baseline is proven best'. That asymmetry is the whole")
    print("  decision: when a spike cannot show a win, the correct action is to keep the")
    print("  simplest thing, and the simplest thing here is also the incumbent. Nothing")
    print("  changes.")
    print()
    print("  WHAT WOULD SETTLE IT: >= 20 identities per domain and >= 5 recordings each")
    print("  (>= 100 LOO trials), impostor scores drawn from MANY subjects rather than one")
    print("  (the donateacry cohort supplies 421 recordings across ~207 infants for exactly")
    print("  this), and thresholds re-derived per candidate on a split disjoint from the one")
    print("  used to rank them. Until that exists, this question stays open rather than")
    print("  answered in the baseline's favour.")
    print()
    print("REPRODUCE: cd %s && . .venv/bin/activate && python tools/aggregation_spike.py"
          % ROOT)
    print()


if __name__ == "__main__":
    main()
