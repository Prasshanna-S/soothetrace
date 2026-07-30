"""Measure whether cry-imitation matching works for PEOPLE IN GENERAL.

WHAT THIS IS NOT: it is not training on anyone. There is no training step in this system.
The encoder is fixed deterministic maths, and enrollment only stores an embedding at runtime.
Nobody's voice is or can be privileged - a stranger enrolled live behaves identically to
someone enrolled a week ago.

WHAT THIS IS: a measurement of one person-independent property - 

    Are one person's imitations more similar to THEIR OWN other imitations
    than to a DIFFERENT person's imitations?

If yes, the mechanism works for everybody. If no, it works for nobody, including whoever ran
the test. Two participants is the minimum that can answer it; three is better because it lets
one of them be an unenrolled stranger.

Recordings go to a SEPARATE trial database and are deleted on request. They are never
enrolled into the demo - the demo enrolls live, in front of the audience, which is both the
honest way and the better piece of theatre.

Usage:
    python tools/imitation_trial.py record  --person alice --takes 3
    python tools/imitation_trial.py record  --person bob   --takes 3
    python tools/imitation_trial.py record  --person carol --takes 1     # the stranger
    python tools/imitation_trial.py analyse [--write-calibration]
    python tools/imitation_trial.py wipe
"""
from __future__ import annotations

import argparse
import glob
import itertools
import os
import re
import shutil
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

import config      # noqa: E402
import encoders    # noqa: E402
import identity    # noqa: E402
import store       # noqa: E402

TRIAL_DIR = os.path.join(config.AUDIO_DIR, "imitation_trial")
SAFE = re.compile(r"[^a-z0-9_-]+")


def consent() -> bool:
    """docs/LIABILITY.md §2 - audio only, and every audible adult consents."""
    print("\nThis records AUDIO ONLY. No video, ever.")
    print("Recordings stay on this machine, are used only to measure whether the method")
    print("works, and can be deleted with:  python tools/imitation_trial.py wipe")
    print("\nDoes this person consent to a short audio-only recording? [y/N] ", end="")
    return input().strip().lower() in ("y", "yes")


def cmd_record(args) -> int:
    name = SAFE.sub("-", args.person.strip().lower()).strip("-")
    if not name:
        print("need a --person name", file=sys.stderr)
        return 1
    os.makedirs(TRIAL_DIR, exist_ok=True)
    if not consent():
        print("Consent not given - nothing recorded.")
        return 1

    print(f"\nRecording {args.takes} imitation(s) for {name!r}.")
    print("Each take: make a baby-cry sound for the whole duration. Take a breath between")
    print("takes - they must be INDEPENDENT performances, not one long cry chopped up,")
    print("or the profile agrees with itself for free and the result means nothing.\n")

    import session   # product workstream's capture path - deliberately the same one the demo uses
    made = 0
    for i in range(1, args.takes + 1):
        existing = len(glob.glob(os.path.join(TRIAL_DIR, f"{name}-*.wav")))
        input(f"  take {i}/{args.takes} - press Enter, then cry for ~{args.seconds:g}s ")
        path = session.record(f"imitation-{name}", args.seconds)
        if not path:
            print("    capture failed, skipping", file=sys.stderr)
            continue
        dest = os.path.join(TRIAL_DIR, f"{name}-{existing + 1:02d}.wav")
        shutil.move(path, dest)
        q = identity.quality(dest)
        usable = encoders.encode(encoders.MFCC87, dest) is not None
        flag = "OK" if usable else "UNUSABLE (too quiet / too short)"
        print(f"    saved {os.path.basename(dest)}  mean {q['mean_db']} dB  "
              f"voiced {q['voiced_fraction']:.0%}  -> {flag}")
        made += usable
    print(f"\n{made} usable take(s) for {name!r}. "
          f"Total in trial set: {len(glob.glob(os.path.join(TRIAL_DIR, '*.wav')))}")
    return 0


def _load():
    """{person: [vector, ...]} - normalized, ready for cosine."""
    files = sorted(glob.glob(os.path.join(TRIAL_DIR, "*.wav")))
    if not files:
        return {}, None
    base = store.get_baseline(config.POPULATION_KEY)
    baseline = (np.asarray(base["mu"]), np.asarray(base["sd"])) if base else None
    if baseline is None:
        print("No population baseline - run tools/build_baseline.py", file=sys.stderr)
        return {}, None
    raw: dict[str, list] = {}
    for f in files:
        person = os.path.basename(f).rsplit("-", 1)[0]
        v = encoders.encode(encoders.MFCC87, f)
        if v is None:
            print(f"  ! {os.path.basename(f)}: unusable, skipped", file=sys.stderr)
            continue
        raw.setdefault(person, []).append(v)
    out = {}
    for person, vs in raw.items():
        out[person] = list(encoders.prepare(encoders.MFCC87, vs, baseline))
    return out, baseline


def cmd_analyse(args) -> int:
    people, _ = _load()
    if not people:
        print(f"No usable recordings in {TRIAL_DIR}", file=sys.stderr)
        return 1
    print(f"\nparticipants: " + ", ".join(f"{p}({len(v)})" for p, v in people.items()))

    enrollable = {p: v for p, v in people.items() if len(v) >= 2}
    single = len(enrollable) < 2

    if single:
        # ONE PERSON IS ENOUGH FOR THE GO/NO-GO. It measures the NECESSARY condition:
        # are one person's independent imitations consistent with each other at all?
        # If they are not, the method is dead and no number of additional people rescues
        # it. If they are, a second person is needed for the SUFFICIENT condition
        # (that different people are actually distinguishable).
        only = next(iter(enrollable), None)
        if only is None or len(people.get(only, [])) < 2:
            print("\nNeed at least 2 usable takes from one person.", file=sys.stderr)
            return 1
        vs = people[only]
        w = np.array([float(a @ b) for a, b in itertools.combinations(vs, 2)])
        print(f"\n=== SINGLE PARTICIPANT - necessary condition only ===")
        print(f"  {only}: {len(vs)} independent takes, {len(w)} pairs")
        print(f"  within-person similarity: mean {w.mean():+.4f}  "
              f"min {w.min():+.4f}  max {w.max():+.4f}")
        # Reference point: how similar are two DIFFERENT infants on the same rig? 0.776.
        # An imitation profile needs to beat that kind of floor to be worth anything.
        print(f"  reference: two DIFFERENT infants on a fixed rig scored 0.776 "
              f"(docs/ACCEPTANCE-RESULTS-02.md)")
        print("\n=== VERDICT (provisional) ===")
        if w.mean() > 0.85 and w.min() > 0.75:
            print("  Your own takes are strongly self-consistent. The NECESSARY condition")
            print("  holds, so the method is worth pursuing.")
            print("  -> Get 2-3 takes from ONE other person to finish this. Until then the")
            print("     imitation flow stays behind conservative thresholds.")
        elif w.mean() > 0.70:
            print("  Moderately self-consistent. Plausible but not convincing - a second")
            print("  person could easily land inside this spread and break it.")
            print("  -> Do not build the visitor flow on this yet.")
        else:
            print(f"  NOT self-consistent (mean {w.mean():+.4f}). Your own imitations do not")
            print("  resemble each other, so nobody's will. A performed cry is a performance,")
            print("  not a stable voice.")
            print("  -> CUT the visitor-imitation flow. The infant identity demo is")
            print("     unaffected and already measured at 13/15 with zero wrong answers.")
        print("\n  (No calibration is written from a single participant - a threshold needs")
        print("   an impostor distribution, and one person cannot provide one.)")
        return 0

    # within-person: every pair of one person's own takes
    within = [float(a @ b) for vs in people.values() for a, b in itertools.combinations(vs, 2)]
    # between-person: every cross pair
    between = [float(a @ b)
               for p, q in itertools.combinations(people, 2)
               for a in people[p] for b in people[q]]
    within, between = np.array(within), np.array(between)

    print("\n=== IS THE METHOD PERSON-SPECIFIC AT ALL? ===")
    print(f"  same person, different takes : n={len(within):3d}  mean {within.mean():+.4f}  "
          f"min {within.min():+.4f}")
    print(f"  different people             : n={len(between):3d}  mean {between.mean():+.4f}  "
          f"max {between.max():+.4f}")
    gap = within.mean() - between.mean()
    separable = within.min() > between.max()
    print(f"  gap {gap:+.4f}   distributions {'DO NOT overlap' if separable else 'OVERLAP'}")

    # leave-one-out identification across everyone with >=2 takes
    print("\n=== LEAVE-ONE-OUT IDENTIFICATION (anyone vs everyone) ===")
    correct = n = 0
    margins_ok, margins_bad = [], []
    for truth, vs in enrollable.items():
        for i, held in enumerate(vs):
            scores = {}
            for p, pv in enrollable.items():
                ens = [v for j, v in enumerate(pv) if not (p == truth and j == i)]
                if ens:
                    scores[p] = float(np.mean([v @ held for v in ens]))
            ranked = sorted(scores.items(), key=lambda kv: -kv[1])
            pred, top = ranked[0]
            runner = ranked[1][1] if len(ranked) > 1 else -1.0
            margin = top - runner
            n += 1
            ok = pred == truth
            correct += ok
            (margins_ok if ok else margins_bad).append(margin)
            print(f"    {truth}[{i+1}] -> {pred:10} {'OK  ' if ok else 'MISS'}  "
                  f"top {top:+.4f}  margin {margin:+.4f}")
    acc = correct / n if n else 0.0
    chance = 1.0 / len(enrollable)
    print(f"\n  {correct}/{n} = {acc:.1%}   (chance {chance:.1%} with "
          f"{len(enrollable)} people)")

    print("\n=== VERDICT ===")
    if acc >= 0.9 and gap > 0.05:
        print("  Imitation matching WORKS, and it works on whoever was recorded - which is")
        print("  the point: nothing is trained on anyone. Enroll visitors live.")
        ok = True
    elif acc > chance + 0.15:
        print(f"  Partial signal ({acc:.0%} vs {chance:.0%} chance). Usable with the margin")
        print("  gate returning `uncertain` on close calls, but expect retries on stage.")
        ok = True
    else:
        print(f"  NOT working ({acc:.0%} vs {chance:.0%} chance). Two imitations by one")
        print("  person are a performance, not a stable voice. CUT the visitor-imitation")
        print("  flow - the infant identity demo is unaffected and already measured.")
        ok = False

    if args.write_calibration and ok and margins_ok:
        if margins_bad and max(margins_bad) >= min(margins_ok):
            margin_thr = round(float(max(margins_bad)) + 0.01, 4)
        else:
            margin_thr = round(float(((max(margins_bad) if margins_bad else 0.0)
                                      + min(margins_ok)) / 2), 4)
        cal = identity.load_calibration()
        cal.setdefault("per_kind", {})[identity.KIND_IMITATION] = {
            "accept_threshold": round(float(np.percentile(within, 10)), 4),
            "margin_threshold": max(0.005, margin_thr),
            "strong_threshold": round(float(np.median(within)), 4),
            "trials": {"people": len(enrollable), "loo_correct": correct, "loo_n": n,
                       "within_mean": round(float(within.mean()), 6),
                       "between_mean": round(float(between.mean()), 6)},
        }
        cal["version"] = cal.get("version", "v") + "+imitation"
        identity.save_calibration(cal)
        print(f"\n  wrote per-kind imitation calibration -> {identity.CALIBRATION_PATH}")
    elif args.write_calibration:
        print("\n  NOT writing calibration - the measurement does not support it.")
    return 0


def cmd_wipe(args) -> int:
    if os.path.isdir(TRIAL_DIR):
        n = len(glob.glob(os.path.join(TRIAL_DIR, "*.wav")))
        shutil.rmtree(TRIAL_DIR)
        print(f"deleted {n} trial recording(s) and {TRIAL_DIR}")
    else:
        print("nothing to delete")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("record"); r.add_argument("--person", required=True)
    r.add_argument("--takes", type=int, default=3)
    r.add_argument("--seconds", type=float, default=6.0)
    r.set_defaults(fn=cmd_record)
    a = sub.add_parser("analyse"); a.add_argument("--write-calibration", action="store_true")
    a.set_defaults(fn=cmd_analyse)
    w = sub.add_parser("wipe"); w.set_defaults(fn=cmd_wipe)
    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
