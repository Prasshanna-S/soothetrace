"""Seed a subject from LIVE recordings through the demo's own rig.

WHY THIS EXISTS - it is the difference between a demo that works and one that fails on stage.

`tools/seed_demo.py` seeds from 2015-era 8 kHz corpus files. If the demo then queries with a
live microphone, that is *exactly* the comparison round 1 measured as failing:

    digital corpus fixture vs live capture   -> -0.258   FAIL
    live capture vs live capture             ->  0.909   PASS

Channel mismatch breaks matching; caregiver speech overlay does not
(`docs/ACCEPTANCE-RESULTS-01.md` B2). So every episode the demo compares must come through
the same microphone, room and gain as the query.

Use `seed_demo.py` to exercise the LOGIC without a mic. Use THIS to prepare a demo.

Usage:
    python tools/seed_live.py <subject_id> --episodes 6 [--seconds 20] [--reset]

For each episode you will be prompted to start the interaction (play a cry, speak to it),
then asked what settled it - the same question a real caregiver answers. Everything runs
through the real pipeline: product workstream's session.finish, not a shortcut.
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

import config          # noqa: E402
import retrieve        # noqa: E402
import session         # noqa: E402
import store           # noqa: E402

RIG_REMINDER = """
RIG - keep every one of these IDENTICAL across seeding and the demo itself.
Changing any of them can break matching (see docs/ACCEPTANCE-02.md test J):
  * same playback device, same distance, same volume
  * same capture device (this machine's mic), same input gain
  * same room, same background noise level
Write the settings down. If you re-seed later in a different room, re-seed ALL of it.
"""


def consent_gate() -> bool:
    """Audio-only, and every audible adult consents. docs/LIABILITY.md §2.

    Georgia is one-party consent for audio, but this asks more than Georgia requires on
    purpose: the moment a second adult is audible, or the recording happens in an all-party
    state, one-party is no longer enough. Never loosen this to speed up testing.
    """
    print("\nThis records AUDIO ONLY. No video, ever.")
    print("Do all audible adults present consent to a brief audio-only recording? [y/N] ", end="")
    return input().strip().lower() in ("y", "yes")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("subject_id")
    ap.add_argument("--episodes", type=int, default=7,
                    help="how many live episodes to seed. Round-2 test I measured 6 PRIOR "
                         "episodes as the point where retrieval becomes useful, so the "
                         "default is 7 - six priors plus one, giving a margin if a capture "
                         "fails")
    ap.add_argument("--seconds", type=float, default=None,
                    help="fixed length per recording; omit to stop each one with Enter")
    ap.add_argument("--reset", action="store_true", help="delete this subject's episodes first")
    args = ap.parse_args()

    store.init_db()
    print(RIG_REMINDER)

    if store.get_baseline(config.POPULATION_KEY) is None:
        print("⚠️  No population baseline. Run tools/build_baseline.py first, or retrieval "
              "will correctly return nothing.\n", file=sys.stderr)

    if args.reset:
        for ep in store.list_episodes(args.subject_id):
            store.delete_episode(ep["id"])
        print(f"reset {args.subject_id!r}\n")

    if not consent_gate():
        print("Consent not given - nothing recorded.")
        return 1

    made = 0
    for i in range(1, args.episodes + 1):
        print(f"\n─── episode {i} of {args.episodes} ───")
        input("Set up the interaction, then press Enter to START recording. ")
        path = session.record(args.subject_id, args.seconds)
        if not path:
            print("  capture failed - skipping this episode", file=sys.stderr)
            continue

        print("\n  What settled it? (plain words, or Enter to skip)")
        print("  Say so honestly if nothing worked - 'nothing worked' is the most")
        print("  important answer in the dataset and must not be recorded as a success.")
        answer = input("  > ").strip() or None

        ep = session.finish(args.subject_id, path, answer)
        if not ep:
            print("  finish() failed - episode not saved", file=sys.stderr)
            continue
        made += 1
        fp_len = len(ep.get("fingerprint") or [])
        print(f"  saved id={ep.get('id')}  fingerprint={fp_len} dims  "
              f"worked={ep.get('worked')}  src={ep.get('outcome_src')}")
        if fp_len != 87:
            print("  ⚠️  fingerprint is not 87 dims - this episode will not match", file=sys.stderr)
        if ep.get("transcript"):
            print(f"  heard: {ep['transcript'][:90]}")
        else:
            print("  ⚠️  empty transcript - interventions cannot be extracted "
                  "without caregiver speech", file=sys.stderr)

    print(f"\n{made} live episodes seeded for {args.subject_id!r}")

    usable = retrieve.episode_count(args.subject_id)
    print(f"usable (fingerprinted) episodes: {usable}")
    if usable < retrieve.MIN_EPISODES_FOR_MATCH + 1:
        print(f"⚠️  Need more than {retrieve.MIN_EPISODES_FOR_MATCH} PRIOR episodes before a "
              f"recall will render. Seed more before demoing.", file=sys.stderr)

    # Sanity-check retrieval against the most recent episode, the way the demo will.
    eps = store.list_episodes(args.subject_id)
    if eps and eps[0].get("fingerprint"):
        q = eps[0]
        matches = retrieve.find_similar(args.subject_id, q["fingerprint"], k=3,
                                        exclude_episode_id=q["id"])
        print(f"\ndry run - querying with episode {q['id']}:")
        if not matches:
            print("  NO MATCHES. The demo will show the 'not enough to compare yet' state.")
        for m in matches:
            print(f"  [{m['band']:>6}] ep {m['episode_id']}  -> {m['outcome']}   "
                  f"(cos {m['similarity']:+.3f}, debug only - never shown to a human)")

    # Mixed-channel guard: the failure this whole tool exists to prevent.
    sources = {("corpus" if not (ep.get("audio_path") or "").startswith(
        os.path.abspath(config.AUDIO_DIR)) else "live")
        for ep in eps if ep.get("audio_path")}
    if len(sources) > 1:
        print("\n🔴 MIXED CHANNELS: this subject has both corpus-sourced and live episodes.\n"
              "   Round 1 measured cross-channel matching at -0.258 (fail) vs 0.909 same-channel.\n"
              "   Use --reset and seed live-only before demoing.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
