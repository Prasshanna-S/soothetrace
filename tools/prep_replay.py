"""Build a LEVEL-MATCHED replay master so every voice traverses an identical channel.

THE PROBLEM THIS SOLVES

The imitation trial currently mixes two different channels:

    Person A:  voice -> phone mic -> WhatsApp                       (direct)
    Person B:  file  -> Mac SPEAKER -> room -> phone mic            (replayed)

Person B's audio carries an entire extra loudspeaker-and-room stage. That is a much larger
difference than two phones, and it is almost certainly what produced the non-overlapping
level ranges (A -23.84..-22.60 dB vs B -24.73..-23.97 dB) reported in the spike. Any
"we can tell these two people apart" result on that data is partly measuring the channel.

THE FIX

Send EVERY file down the SAME path: normalize all sources to an identical RMS, concatenate
them into one master with tone cues between takes, play the master ONCE from the Mac speaker
into the phone, then split the capture at the cues. Every recording then differs only in the
voice - which is the thing we are trying to measure. This is exactly the cue-sequence method
already validated for the round-2 infant corpus.

NOTE ON WHAT THIS TESTS

The demo captures a visitor crying DIRECTLY into the phone, not replayed. So a replayed trial
is a *harder* condition than the demo: replay adds speaker colouration and room reverb to
both voices. If voices separate under replay they should separate better direct. This is
deliberately the conservative direction.

Usage:
    python tools/prep_replay.py --out data/audio/replay_master \\
        data/audio/imitation_trial_sources/prasshanna-0*.wav \\
        data/audio/imitation_trial_sources/control-0*.wav \\
        data/audio/imitation_trial_sources/blind-query-0[12].wav
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

import fingerprint   # noqa: E402

SR = fingerprint.SR
TARGET_RMS_DB = -24.0     # every take lands here exactly; kills the level giveaway
CUE_HZ = 1000.0           # a tone nothing in a cry occupies narrowly
CUE_S = 0.35
GAP_S = 0.60              # silence either side of each cue so splitting is unambiguous


def rms_db(y) -> float:
    return 20.0 * np.log10(float(np.sqrt((y ** 2).mean() + 1e-12)))


def write_wav(path, y, sr=SR):
    y = np.clip(y, -1.0, 1.0).astype(np.float32)
    subprocess.run(["ffmpeg", "-v", "quiet", "-y", "-f", "f32le", "-ac", "1",
                    "-ar", str(sr), "-i", "pipe:0", "-c:a", "pcm_s16le", path],
                   input=y.tobytes(), check=False)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("sources", nargs="+")
    ap.add_argument("--out", default="data/audio/replay_master")
    ap.add_argument("--target-db", type=float, default=TARGET_RMS_DB)
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    cue = (0.35 * np.sin(2 * np.pi * CUE_HZ * np.arange(int(CUE_S * SR)) / SR)).astype(np.float32)
    gap = np.zeros(int(GAP_S * SR), dtype=np.float32)

    master, manifest = [], []
    # lead-in so the first cue is never clipped by a late playback start
    master.append(np.zeros(int(1.5 * SR), dtype=np.float32))
    cursor = 1.5

    print(f"target RMS {args.target_db:+.1f} dB - every take normalized to the SAME level\n")
    for src in args.sources:
        y = fingerprint.load_audio(src)
        if y is None or len(y) < int(0.5 * SR):
            print(f"  ! {os.path.basename(src)}: unusable, skipped", file=sys.stderr)
            continue
        before = rms_db(y)
        y = y * (10 ** ((args.target_db - before) / 20.0))
        peak = float(np.abs(y).max())
        if peak > 0.98:                      # avoid clipping after the gain change
            y = y * (0.98 / peak)
        after = rms_db(y)
        stem = os.path.splitext(os.path.basename(src))[0]
        norm_path = os.path.join(args.out, f"norm-{stem}.wav")
        write_wav(norm_path, y)

        master += [cue, gap, y, gap]
        start = cursor + CUE_S + GAP_S
        manifest.append({"stem": stem, "source": src, "start_s": round(start, 4),
                         "duration_s": round(len(y) / SR, 4),
                         "rms_before_db": round(before, 2), "rms_after_db": round(after, 2),
                         "peak_after": round(peak, 3)})
        cursor = start + len(y) / SR + GAP_S
        print(f"  {stem:30} {before:+7.2f} -> {after:+7.2f} dB   "
              f"starts at {start:7.2f}s   {len(y)/SR:5.2f}s")

    if not manifest:
        print("nothing to do", file=sys.stderr)
        return 1

    master.append(np.zeros(int(1.0 * SR), dtype=np.float32))
    y = np.concatenate(master)
    master_path = os.path.join(args.out, "REPLAY-MASTER.wav")
    write_wav(master_path, y)
    with open(os.path.join(args.out, "manifest.json"), "w") as fh:
        json.dump({"sample_rate": SR, "cue_hz": CUE_HZ, "cue_s": CUE_S, "gap_s": GAP_S,
                   "target_rms_db": args.target_db, "takes": manifest}, fh, indent=1)

    spread = max(m["rms_after_db"] for m in manifest) - min(m["rms_after_db"] for m in manifest)
    print(f"\nmaster: {master_path}  ({len(y)/SR:.1f}s, {len(manifest)} takes)")
    print(f"level spread after normalization: {spread:.2f} dB "
          f"({'GOOD - the giveaway is gone' if spread < 0.5 else 'still too wide'})")
    print(f"manifest: {os.path.join(args.out, 'manifest.json')}")
    print(f"""
NEXT - this is the part that makes the trial valid:

  1. python tools/rig_check.py --seconds 5        # must print RIG OK; write the rig down
  2. Play {os.path.basename(master_path)} ONCE from the Mac speaker at a FIXED volume.
  3. Record the whole thing on the phone in ONE take. Do not move anything mid-playback.
  4. Split the capture at the 1 kHz cues using manifest.json offsets, and save as
     data/audio/imitation_trial/<person>-NN.wav
  5. python tools/imitation_trial.py analyse

Every take now shares one speaker, one room, one mic, one gain and one level. The ONLY
remaining difference between the two people is the voice. That is the whole point - a result
on the current mixed-channel set cannot distinguish voice from channel, and this can.
""")
    return 0


if __name__ == "__main__":
    sys.exit(main())
