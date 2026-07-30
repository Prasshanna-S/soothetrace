"""Seed a demo subject from the public corpus - no microphone required.

Picks the corpus infant with the MOST separate recordings (a device UUID = one family's
phone) and replays those recordings as sequential episodes for one subject, with plausible
caregiver interventions and outcomes attached.

This exists so the retrieval loop can be exercised end to end before product workstream's mic capture
lands, and so the demo has a deterministic fallback that does not depend on a live baby.

⚠️ The interventions/outcomes seeded here are SYNTHETIC. They are labelled as such in the
`outcome_src` field ('seed'). Never present seeded data to anyone as a real result
(docs/LIABILITY.md §7).

Usage:
    python tools/build_baseline.py     # once
    python tools/seed_demo.py [subject_id] [--reset]
"""
import collections
import glob
import os
import re
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
import config          # noqa: E402
import fingerprint     # noqa: E402
import retrieve        # noqa: E402
import store           # noqa: E402

CORPUS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "experiments", "donateacry-corpus",
                      "donateacry_corpus_cleaned_and_updated_data")
UUID_RE = re.compile(r"^([0-9A-Fa-f-]{36})-(\d+)-")

# Synthetic caregiver behaviour, cycled. Evidence spans are marked synthetic on purpose - 
# a real Intervention's `evidence` must be a literal transcript span.
SCRIPTS = [
    ("Oh sweetie, what's wrong? Are you hungry? Okay, let me get your bottle.",
     [("checked on baby", "what's wrong"), ("offered bottle", "let me get your bottle")],
     "fed him", True),
    ("Let's check your diaper. No? Okay, let me try rocking you.",
     [("checked diaper", "check your diaper"), ("rocked baby", "try rocking you")],
     "rocking worked", True),
    ("Are you tired? Let me swaddle you and turn the white noise on.",
     [("swaddled", "swaddle you"), ("white noise", "turn the white noise on")],
     "white noise settled him", True),
    ("Shh, it's okay. Let me pick you up. Still crying... let me feed you.",
     [("picked up", "let me pick you up"), ("fed", "let me feed you")],
     "fed him", True),
    ("I've tried everything. Let me walk with you a bit.",
     [("walked with baby", "walk with you")],
     "nothing worked, he cried himself out", False),
]


def corpus_subject_files() -> list[str]:
    """Recordings of the single infant with the most separate episodes."""
    by_uuid = collections.defaultdict(list)
    for p in sorted(glob.glob(os.path.join(CORPUS, "*", "*.wav"))):
        m = UUID_RE.match(os.path.basename(p))
        if m:
            by_uuid[m.group(1).lower()].append(p)
    if not by_uuid:
        return []
    uuid, files = max(by_uuid.items(), key=lambda kv: len(kv[1]))
    print(f"corpus infant {uuid[:8]}... with {len(files)} separate recordings")
    return files


def main() -> int:
    subject = next((a for a in sys.argv[1:] if not a.startswith("-")), "baby-demo")
    reset = "--reset" in sys.argv

    files = corpus_subject_files()
    if not files:
        print(f"No corpus at {CORPUS}\n  cd experiments && git clone --depth 1 "
              f"https://github.com/gveres/donateacry-corpus.git", file=sys.stderr)
        return 1

    store.init_db()
    if reset:
        for ep in store.list_episodes(subject):
            store.delete_episode(ep["id"])
        print(f"reset subject {subject!r}")

    if store.get_baseline(config.POPULATION_KEY) is None:
        print("⚠️  no population baseline - run tools/build_baseline.py first, or "
              "retrieval will correctly return nothing.", file=sys.stderr)

    # Space episodes across evenings: crying has a documented ~7-8pm peak (RESEARCH §1).
    start = datetime.now(timezone.utc).astimezone() - timedelta(days=len(files))
    prev_at = None
    made = 0
    for i, path in enumerate(files):
        fp = fingerprint.compute_windowed(path)
        if fp is None:
            continue
        transcript, ivs, outcome, worked = SCRIPTS[i % len(SCRIPTS)]
        at = (start + timedelta(days=i)).replace(hour=19, minute=20 + (i * 7) % 30)
        ep_id = store.save_episode({
            "subject_id": subject,
            "started_at": at.isoformat(),
            "duration_s": fingerprint.duration_s(path),
            "audio_path": path,
            "fingerprint": fp,
            "transcript": transcript,
            "interventions": [
                {"order": n + 1, "action": a, "evidence": e}
                for n, (a, e) in enumerate(ivs)
            ],
            "outcome": outcome,
            "outcome_src": "seed",       # NOT 'caregiver' - this data is synthetic
            "worked": worked,
            "context": fingerprint.build_context(
                at.isoformat(), prev_at, subject_age_days=30 + i),
        })
        prev_at = at.isoformat()
        made += 1
        print(f"  episode {ep_id}: {at:%a %d %b %H:%M}  {os.path.basename(path)[:22]}..."
              f"  -> {outcome}")

    print(f"\n{made} episodes seeded for {subject!r}")

    # Exercise retrieval with the most recent episode as the query.
    eps = store.list_episodes(subject)
    if eps:
        q = eps[0]
        matches = retrieve.find_similar(subject, q["fingerprint"],
                                        k=3, exclude_episode_id=q["id"])
        print(f"\nquery = episode {q['id']} ({q['started_at'][:16]})")
        if not matches:
            print(f"  no matches - {retrieve.episode_count(subject)} episodes on record "
                  f"(need {retrieve.MIN_EPISODES_FOR_MATCH} priors, and a baseline)")
        for m in matches:
            print(f"  [{m['band']:>6}] ep {m['episode_id']} {m['started_at'][:16]} "
                  f"-> {m['outcome']}   (cos {m['similarity']:+.3f}, debug only)")
        print("\nintervention tally (T2 payload):")
        for t in retrieve.intervention_tally(subject):
            print(f"  {t['action']:<22} worked {t['worked']}/{t['tried']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
