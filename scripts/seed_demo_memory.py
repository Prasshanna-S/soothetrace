"""Seed clearly synthetic care-memory history for the three infant demo profiles."""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src import config, fingerprint, identity, store  # noqa: E402


SEED_VERSION = "profile-care-memory-v1"
TARGET_PROFILE_NAMES = ("Baby 1", "Baby 2", "Baby 3")
EPISODES = (
    {
        "hour": 19,
        "minute": 10,
        "tags": ["last_feed_over_4h", "evening"],
        "transcript": "I offered a bottle and the baby settled after feeding.",
        "interventions": [("offered bottle", "offered a bottle")],
        "outcome": "Bottle feeding settled the baby.",
        "worked": True,
    },
    {
        "hour": 20,
        "minute": 5,
        "tags": ["recent_diaper", "evening"],
        "transcript": "I changed the diaper, but the crying continued.",
        "interventions": [("changed diaper", "changed the diaper")],
        "outcome": "The diaper change did not settle the baby.",
        "worked": False,
    },
    {
        "hour": 2,
        "minute": 20,
        "tags": ["awake_over_4h", "overnight"],
        "transcript": "I rocked the baby slowly and the crying eased.",
        "interventions": [("rocked baby", "rocked the baby slowly")],
        "outcome": "Slow rocking settled the baby.",
        "worked": True,
    },
    {
        "hour": 18,
        "minute": 45,
        "tags": ["awake_2_to_4h", "evening"],
        "transcript": (
            "I swaddled the baby and turned on white noise. The baby settled."
        ),
        "interventions": [
            ("swaddled baby", "swaddled the baby"),
            ("turned on white noise", "turned on white noise"),
        ],
        "outcome": "Swaddling with white noise settled the baby.",
        "worked": True,
    },
    {
        "hour": 21,
        "minute": 15,
        "tags": ["evening", "caregiver-noted-restless"],
        "transcript": "I walked with the baby, but the crying continued.",
        "interventions": [("walked with baby", "walked with the baby")],
        "outcome": "Walking did not settle the baby.",
        "worked": False,
    },
    {
        "hour": 3,
        "minute": 5,
        "tags": ["last_feed_under_2h", "overnight"],
        "transcript": "I held the baby upright and the baby settled.",
        "interventions": [("held baby upright", "held the baby upright")],
        "outcome": "Being held upright settled the baby.",
        "worked": True,
    },
)


class SeedDemoError(RuntimeError):
    """The requested demo-memory seed could not be created safely."""


def _care_memory_reference(enrollment_path: str) -> Path:
    reference = Path(enrollment_path).expanduser().resolve()
    canonical = reference.with_name("canonical.wav")
    if reference.name.casefold() == "identity.wav" and canonical.is_file():
        return canonical.resolve()
    return reference


def _discover_profiles(db_path: str) -> dict[str, tuple[dict, list[Path]]]:
    profiles = identity.list_profiles(db_path)
    discovered = {}
    for name in TARGET_PROFILE_NAMES:
        matches = [
            profile
            for profile in profiles
            if profile.get("display_name") == name
            and profile.get("kind") == identity.KIND_INFANT
        ]
        if not matches:
            raise SeedDemoError(f"required infant profile {name!r} was not found")
        if len(matches) > 1:
            raise SeedDemoError(f"multiple active infant profiles are named {name!r}")

        profile = matches[0]
        references = [
            _care_memory_reference(path)
            for path in identity.profile_reference_audio(profile["id"], db_path)
        ]
        usable = [
            path
            for path in references
            if path.is_file() and path.suffix.casefold() == ".wav"
        ]
        if len(usable) < 3:
            raise SeedDemoError(
                f"{name} requires at least 3 usable enrolled WAV references; "
                f"found {len(usable)}"
            )
        discovered[name] = (profile, usable[:3])
    return discovered


def _existing_seed_slots(subject_id: str, db_path: str) -> set[int]:
    slots = set()
    for episode in store.list_episodes(subject_id, db_path):
        context = episode.get("context")
        if (
            episode.get("outcome_src") != "seed"
            or not isinstance(context, dict)
            or context.get("demo_seed") is not True
            or context.get("demo_seed_version") != SEED_VERSION
        ):
            continue
        slot = context.get("demo_seed_slot")
        if isinstance(slot, int) and not isinstance(slot, bool) and 1 <= slot <= 6:
            slots.add(slot)
    return slots


def _episode_times(now: datetime) -> list[datetime]:
    times = []
    for slot, scenario in enumerate(EPISODES, start=1):
        times.append(
            (now - timedelta(days=8 - slot)).replace(
                hour=scenario["hour"],
                minute=scenario["minute"],
                second=0,
                microsecond=0,
            )
        )
    return times


def _fingerprint_reference(path: Path) -> tuple[list[float], float]:
    acoustic = fingerprint.compute_windowed(str(path))
    duration = fingerprint.duration_s(str(path))
    if acoustic is None or len(acoustic) != fingerprint.DIM or duration is None:
        raise SeedDemoError(f"enrolled reference has no usable acoustic signal: {path}")
    return acoustic, duration


def seed_demo_memory(
    db_path: str | Path | None = None,
    data_root: str | Path | None = None,
) -> dict:
    """Create six synthetic prior episodes for each named infant profile.

    Existing rows are never deleted. Rows created by this tool carry a stable
    version-and-slot marker so rerunning the command fills only missing slots.
    """
    database = str(Path(db_path or config.DB_PATH).expanduser().resolve())
    managed_root = Path(data_root or config.AUDIO_DIR).expanduser().resolve()
    store.init_db(database)

    discovered = _discover_profiles(database)
    now = datetime.now(timezone.utc).astimezone()
    times = _episode_times(now)
    summary = {"created": 0, "existing": 0, "profiles": {}}

    profile_state = {}
    for name, (profile, references) in discovered.items():
        subject_id = f"profile-{profile['id']}"
        existing_slots = _existing_seed_slots(subject_id, database)
        needed_reference_indexes = {
            (slot - 1) % len(references)
            for slot in range(1, len(EPISODES) + 1)
            if slot not in existing_slots
        }
        prepared = {
            index: _fingerprint_reference(references[index])
            for index in needed_reference_indexes
        }
        profile_state[name] = (
            profile,
            references,
            subject_id,
            existing_slots,
            prepared,
        )

    for name in TARGET_PROFILE_NAMES:
        profile, references, subject_id, existing_slots, prepared = profile_state[name]
        created_for_profile = 0
        previous_at = None
        for slot, (scenario, started_at) in enumerate(
            zip(EPISODES, times),
            start=1,
        ):
            started_at_text = started_at.isoformat()
            if slot in existing_slots:
                previous_at = started_at_text
                continue

            reference_index = (slot - 1) % len(references)
            source = references[reference_index]
            target = (
                managed_root
                / "demo-memory"
                / f"profile-{profile['id']}"
                / f"{SEED_VERSION}-episode-{slot:02d}.wav"
            )
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            acoustic, duration = prepared[reference_index]
            transcript = f"SYNTHETIC DEMO MEMORY: {scenario['transcript']}"
            episode_context = fingerprint.build_context(
                started_at_text,
                previous_at,
                subject_age_days=90 + slot,
            )
            episode_context.update(
                {
                    "tags": list(scenario["tags"]),
                    "demo_seed": True,
                    "demo_seed_version": SEED_VERSION,
                    "demo_seed_slot": slot,
                    "demo_seed_source_enrollment_index": reference_index + 1,
                    "demo_seed_source_audio_sha256": hashlib.sha256(
                        source.read_bytes()
                    ).hexdigest(),
                }
            )
            try:
                episode_id = store.save_episode(
                    {
                        "subject_id": subject_id,
                        "started_at": started_at_text,
                        "duration_s": duration,
                        "audio_path": str(target.resolve()),
                        "fingerprint": acoustic,
                        "transcript": transcript,
                        "interventions": [
                            {
                                "order": order,
                                "action": action,
                                "evidence": evidence,
                            }
                            for order, (action, evidence) in enumerate(
                                scenario["interventions"],
                                start=1,
                            )
                        ],
                        "outcome": f"Synthetic demo outcome: {scenario['outcome']}",
                        "outcome_src": "seed",
                        "worked": scenario["worked"],
                        "context": episode_context,
                    },
                    database,
                )
            except Exception:
                target.unlink(missing_ok=True)
                raise
            if not episode_id:
                target.unlink(missing_ok=True)
                raise SeedDemoError(
                    f"failed to save synthetic episode {slot} for {name}"
                )
            created_for_profile += 1
            summary["created"] += 1
            previous_at = started_at_text

        existing_for_profile = len(existing_slots)
        summary["existing"] += existing_for_profile
        summary["profiles"][name] = {
            "profile_id": profile["id"],
            "subject_id": subject_id,
            "created": created_for_profile,
            "existing": existing_for_profile,
        }
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Seed six clearly synthetic care-memory episodes for Baby 1, Baby 2, "
            "and Baby 3."
        )
    )
    parser.add_argument(
        "--db",
        default=config.DB_PATH,
        help="SQLite database containing the enrolled infant profiles",
    )
    parser.add_argument(
        "--data-root",
        default=config.AUDIO_DIR,
        help="managed audio root for copied demo-memory WAV files",
    )
    args = parser.parse_args(argv)
    try:
        result = seed_demo_memory(args.db, args.data_root)
    except (OSError, SeedDemoError) as exc:
        print(f"seed demo memory failed: {exc}", file=sys.stderr)
        return 1
    print(
        f"{result['created']} synthetic demo-memory episodes created; "
        f"{result['existing']} already present."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
