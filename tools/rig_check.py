"""THE TEST STOPPER. Run this before recording anything for ACCEPTANCE-02 tests H or J.

It records a few seconds through the real capture path, checks the audio is actually usable,
fingerprints it, and prints a RIG BLOCK to paste into the results file.

Why it exists: tests H and J require 16+ recordings through an IDENTICAL rig. If the capture
device is wrong, the level is too low, or the mic is muted, you find out AFTER recording all of
them - and worse, a silently-bad rig turns H2 into the cross-channel comparison that already
measured -0.258, so we would read a thesis failure where there is none.

Specific trap on this machine: avfoundation `:0` is "Realtek USB2.0 Audio", NOT the built-in
microphone, and `session._capture_wav` defaults to `:0`.

Exit 0 = safe to start recording. NON-ZERO = STOP, fix the rig, run again.

Usage:
    python tools/rig_check.py                 # 5 s check on the default device
    IM_AUDIO_DEVICE=':1' python tools/rig_check.py --seconds 8
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

import config          # noqa: E402
import fingerprint     # noqa: E402
import store           # noqa: E402

PROBLEMS: list[str] = []


def bad(msg: str) -> None:
    PROBLEMS.append(msg)
    print(f"  \033[31m✗ {msg}\033[0m")


def good(msg: str) -> None:
    print(f"  \033[32m✓\033[0m {msg}")


def note(msg: str) -> None:
    print(f"  \033[33m!\033[0m {msg}")


def devices() -> list[tuple[str, str]]:
    try:
        p = subprocess.run(["ffmpeg", "-hide_banner", "-f", "avfoundation",
                            "-list_devices", "true", "-i", ""],
                           capture_output=True, timeout=15)
        text = (p.stderr or b"").decode("utf-8", "replace")
    except (OSError, subprocess.SubprocessError):
        return []
    out, in_audio = [], False
    for raw in text.splitlines():
        line = re.sub(r"^\[AVFoundation indev @ [^\]]*\]\s*", "", raw).strip()
        low = line.lower()
        if low.startswith("avfoundation audio devices"):
            in_audio = True
            continue
        if low.startswith("avfoundation video devices"):
            in_audio = False
            continue
        m = re.match(r"^\[(\d+)\]\s+(.*)$", line)
        if in_audio and m:
            out.append((m.group(1), m.group(2)))
    return out


def level_db(wav: str) -> tuple[float, float] | None:
    """(mean_dB, peak_dB) via ffmpeg volumedetect."""
    try:
        p = subprocess.run(["ffmpeg", "-i", wav, "-af", "volumedetect", "-f", "null", "-"],
                           capture_output=True, timeout=30)
        text = (p.stderr or b"").decode("utf-8", "replace")
    except (OSError, subprocess.SubprocessError):
        return None
    mean = re.search(r"mean_volume:\s*(-?[\d.]+) dB", text)
    peak = re.search(r"max_volume:\s*(-?[\d.]+) dB", text)
    if not (mean and peak):
        return None
    return float(mean.group(1)), float(peak.group(1))


def seeded_level(subject_id: str) -> tuple[float, int] | None:
    """Mean capture level of a subject's already-stored episodes, in dB.

    ⚠️ CORRECTED 2026-07-29. An earlier version of this docstring and the warnings below
    claimed 3.9 dB as "the measured breaking point". product workstream's exact levels disprove that:

        J0 reference     -26.8 dB            0.932811  weak
        J1 ~1 m distance -33.5 dB  (-6.7)    0.915141  weak   PRESERVED
        J2 volume 50%    -30.7 dB  (-3.9)    0.896582  none   BROKEN

    A LARGER level drop survived while a SMALLER one broke. Level drift is therefore
    NOT monotonic and there is no validated dB threshold. Treat this check as a smoke
    alarm for gross capture problems (wrong device, muted mic, moved rig) - not as a
    calibrated predictor of whether a match will hold.

    The likely real driver is spectral SHAPE, not level: moving further away mostly
    scales the signal, whereas driving the speaker at 50% changes its frequency response
    and distortion, which moves the MFCCs. Hypothesis, not yet measured.

    ACTIONABLE RULE until the CMN A/B settles it: never change the PLAYBACK volume
    between seeding and querying. Distance appears more forgiving than volume.
    """
    levels = []
    for ep in store.list_episodes(subject_id):
        p = ep.get("audio_path")
        if p and os.path.exists(p):
            lv = level_db(p)
            if lv:
                levels.append(lv[0])
    if not levels:
        return None
    return sum(levels) / len(levels), len(levels)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=5.0)
    ap.add_argument("--subject", default=None,
                    help="compare today's capture level against this subject's already-seeded "
                         "episodes. STRONGLY recommended before a demo - level is the one "
                         "variation measured to break matching.")
    ap.add_argument("--drift-db", type=float, default=2.5,
                    help="warn above this level drift; J measured 3.9 dB as enough to break "
                         "a match, so the default leaves margin")
    args = ap.parse_args()

    print("=" * 64)
    print(" RIG CHECK - run before recording for ACCEPTANCE-02 H / J")
    print("=" * 64)

    # 1. device resolution
    print("\n1. Capture device")
    devs = devices()
    selected = os.environ.get("IM_AUDIO_DEVICE", ":0")
    idx = selected.lstrip(":").split(":")[0]
    if not devs:
        bad("no audio input devices found - check System Settings > Privacy > Microphone")
    else:
        for i, name in devs:
            print(f"      [{i}] {name}" + ("   <-- WILL BE USED" if i == idx else ""))
        chosen = dict(devs).get(idx)
        if chosen is None:
            bad(f"IM_AUDIO_DEVICE={selected} does not exist")
        else:
            good(f"device {selected} = {chosen!r}")
            builtin = [i for i, n in devs if "macbook" in n.lower() and "mic" in n.lower()]
            if builtin and idx not in builtin:
                note(f"this is NOT the built-in mic (index {builtin[0]}). Acceptable only if "
                     f"deliberate AND unchanged for every recording in the run.")
                note(f"to use the built-in mic:  export IM_AUDIO_DEVICE=':{builtin[0]}'")

    # 2. baseline must exist or every query returns nothing
    print("\n2. Normalization baseline")
    store.init_db()
    pop = store.get_baseline(config.POPULATION_KEY)
    if pop and pop.get("n", 0) >= 100:
        good(f"population baseline present (n={pop['n']})")
    else:
        bad("no usable population baseline - run tools/build_baseline.py, or every query "
            "returns [] and H2 will look like a failure when it is a setup error")

    # 3. the real test: capture, then fingerprint
    print(f"\n3. Live capture test ({args.seconds:g}s)")
    print("   Make NOISE for the whole time - talk, or play the cry you will use.")
    input("   Press Enter to start... ")
    with tempfile.TemporaryDirectory() as d:
        wav = os.path.join(d, "rigcheck.wav")
        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error",
               "-f", "avfoundation", "-i", selected, "-t", str(args.seconds),
               "-ac", "1", "-ar", str(config.SAMPLE_RATE), "-c:a", "pcm_s16le", "-y", wav]
        try:
            p = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True,
                               timeout=args.seconds + 30)
        except (OSError, subprocess.SubprocessError) as exc:
            bad(f"capture crashed: {exc}")
            p = None
        if p is not None and p.returncode != 0:
            err = (p.stderr or b"").decode("utf-8", "replace").strip().splitlines()
            bad(f"ffmpeg failed: {err[-1] if err else 'unknown error'}")
        elif not os.path.exists(wav) or os.path.getsize(wav) == 0:
            bad("capture produced no audio")
        else:
            good(f"captured {os.path.getsize(wav)/1024:.0f} KB")

            lv = level_db(wav)
            if lv is None:
                note("could not measure level")
            else:
                mean, peak = lv
                print(f"      mean {mean:.1f} dB / peak {peak:.1f} dB")
                if peak < -40:
                    bad("essentially silent - mic muted, wrong device, or no permission")
                elif mean < -45:
                    bad(f"far too quiet (mean {mean:.1f} dB). Fingerprints need voiced frames "
                        f"above -32 dB; most of this will be discarded as silence")
                elif mean < -35:
                    note(f"quiet (mean {mean:.1f} dB) - move the source closer or raise gain")
                elif peak > -1.0:
                    note(f"peak {peak:.1f} dB is near clipping - lower the volume")
                else:
                    good(f"level healthy (mean {mean:.1f} dB, peak {peak:.1f} dB)")

                # THE check that matters most before a demo. See seeded_level().
                if args.subject:
                    ref = seeded_level(args.subject)
                    if ref is None:
                        note(f"no stored audio for {args.subject!r} to compare against - "
                             f"seed first with tools/seed_live.py")
                    else:
                        ref_mean, n = ref
                        drift = mean - ref_mean
                        print(f"      seeded reference: {ref_mean:.1f} dB "
                              f"(mean of {n} episode(s))   drift: {drift:+.1f} dB")
                        # No validated dB threshold exists - J1 (-6.7 dB) survived while
                        # J2 (-3.9 dB) broke. So: large drift = something is grossly wrong
                        # with the rig; small drift = no signal either way.
                        if abs(drift) >= 10.0:
                            bad(f"level drift {drift:+.1f} dB - that is a gross rig change "
                                f"(wrong device, moved setup, or muted source), not normal "
                                f"variation. Fix the rig or RE-SEED.")
                        elif abs(drift) >= args.drift_db:
                            note(f"level drift {drift:+.1f} dB. There is NO validated dB "
                                 f"threshold (J1 survived -6.7 dB; J2 broke at -3.9 dB), so "
                                 f"this is advisory. What matters: did the PLAYBACK VOLUME "
                                 f"change since seeding? If so, put it back.")
                        else:
                            good(f"level close to the seeded episodes (drift {drift:+.1f} dB)")

            fp = fingerprint.compute_windowed(wav)
            if fp is None:
                bad("FINGERPRINT FAILED on live audio - under 0.3s of voiced content. "
                    "The capture path cannot produce a usable episode.")
            elif len(fp) != fingerprint.DIM:
                bad(f"fingerprint is {len(fp)} dims, expected {fingerprint.DIM}")
            else:
                good(f"fingerprint OK - {len(fp)} dims from live audio "
                     "(capture -> feature path works end to end)")

    # 4. the block to paste into the results file
    print("\n" + "=" * 64)
    if PROBLEMS:
        print(f" 🔴 STOP - {len(PROBLEMS)} problem(s). Do NOT start recording.")
        for pr in PROBLEMS:
            print(f"    - {pr}")
        print("=" * 64)
        return 1

    dev_name = dict(devs).get(idx, "unknown")
    print(" ✅ RIG OK - safe to start recording.\n")
    print(" Paste this into docs/ACCEPTANCE-RESULTS-02.md and DO NOT change any of it")
    print(" mid-run. Fill in the blanks by hand:\n")
    print(" ```")
    print(" RIG")
    print(f"   capture device : {selected} ({dev_name})")
    print(f"   sample rate    : {config.SAMPLE_RATE} Hz mono")
    print(f"   baseline       : population n={pop['n'] if pop else '?'}")
    print("   playback device: ______________________")
    print("   distance       : ______ cm")
    print("   playback volume: ______ (system %/notches)")
    print("   room           : ______________________")
    print("   background     : ______________________")
    print(" ```")
    print("\n Without this block the H and J numbers are not reproducible.")
    print("=" * 64)
    return 0


if __name__ == "__main__":
    sys.exit(main())
