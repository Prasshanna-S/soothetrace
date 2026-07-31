"""Prepare the two-profile phone demo and its distinct synthetic memory stories."""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
import wave
from datetime import datetime, timedelta
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src import audio_ingest, config, fingerprint, identity, store  # noqa: E402


SEED_VERSION = "demo-baby-distinct-memory-v1"
DEMO_PROFILE = "Demo Baby"
LEARNING_PROFILE = "Learning Baby"
DEFAULT_ASSETS_ROOT = REPO_ROOT / "demo_assets" / "baby_audio" / "warning-demo"
DEFAULT_BASELINE_DB = REPO_ROOT / "data" / "episodes.db"

PROFILE_ASSETS = {
    DEMO_PROFILE: (
        "enrollment/demo-baby-x1.wav",
        "enrollment/demo-baby-x2.wav",
        "enrollment/demo-baby-x3.wav",
    ),
    LEARNING_PROFILE: (
        "enrollment/learning-baby-y1.wav",
        "enrollment/learning-baby-y2.wav",
        "enrollment/learning-baby-y4.wav",
    ),
}

MEMORY_GROUPS = (
    {
        "source": "x4",
        "asset": "demo-baby-x4-extended-playback.wav",
        "minute": 0,
        "action": "offered bottle",
        "evidence": "offered a bottle",
        "outcome": "Synthetic demo outcome: Bottle feeding settled the baby.",
    },
    {
        "source": "x7",
        "asset": "demo-baby-x7-extended-playback.wav",
        "minute": 10,
        "action": "held baby upright",
        "evidence": "held the baby upright",
        "outcome": "Synthetic demo outcome: Being held upright settled the baby.",
    },
    {
        "source": "x8",
        "asset": "demo-baby-x8-extended-playback.wav",
        "minute": 20,
        "action": "turned on white noise",
        "evidence": "turned on white noise",
        "outcome": "Synthetic demo outcome: White noise settled the baby.",
    },
)


class PrepareCareDemoError(RuntimeError):
    """The controlled care demo could not be prepared safely."""


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _required_assets(assets_root: Path) -> list[Path]:
    paths = [
        assets_root / relative
        for relatives in PROFILE_ASSETS.values()
        for relative in relatives
    ]
    paths.extend(assets_root / group["asset"] for group in MEMORY_GROUPS)
    missing = [path for path in paths if not path.is_file()]
    if missing:
        rendered = ", ".join(str(path) for path in missing)
        raise PrepareCareDemoError(f"required demo audio is missing: {rendered}")
    return paths


def _ensure_population_baseline(database: str, baseline_db: Path) -> bool:
    if store.get_baseline(config.POPULATION_KEY, database):
        return False
    if not baseline_db.is_file():
        raise PrepareCareDemoError(
            f"population baseline database was not found: {baseline_db}"
        )
    baseline = store.get_baseline(config.POPULATION_KEY, str(baseline_db))
    if not baseline:
        raise PrepareCareDemoError(
            f"population baseline is unavailable in: {baseline_db}"
        )
    store.save_baseline(
        config.POPULATION_KEY,
        baseline["mu"],
        baseline["sd"],
        baseline["n"],
        database,
    )
    return True


def _ensure_profile(name: str, database: str) -> tuple[dict, bool]:
    matches = [
        profile
        for profile in identity.list_profiles(database)
        if profile.get("display_name") == name
        and profile.get("status") != "archived"
    ]
    if len(matches) > 1:
        raise PrepareCareDemoError(f"multiple active profiles are named {name!r}")
    if matches:
        profile = matches[0]
        if profile.get("kind") != identity.KIND_INFANT:
            raise PrepareCareDemoError(
                f"profile {name!r} exists but is not an infant profile"
            )
        return profile, False
    profile = identity.create_profile(
        name,
        kind=identity.KIND_INFANT,
        db_path=database,
    )
    if not profile:
        raise PrepareCareDemoError(f"could not create profile {name!r}")
    return profile, True


def _copy_if_needed(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_file() and _digest(target) == _digest(source):
        return
    shutil.copyfile(source, target)


def _copy_browser_normalized(
    source: Path,
    target: Path,
    data_root: Path,
) -> None:
    """Copy the same identity WAV that a browser enrollment would persist."""
    ingested = audio_ingest.ingest_audio(
        source.read_bytes(),
        "audio/wav",
        capture_metadata={"capture_device_name": "validated fixed rig playback"},
        storage_root=data_root,
    )
    identity_path = ingested.get("identity_path")
    if (
        ingested.get("status") != "ready"
        or not isinstance(identity_path, str)
        or not Path(identity_path).is_file()
    ):
        raise PrepareCareDemoError(
            f"could not normalize enrollment {source.name}: "
            f"{ingested.get('reason') or ingested.get('status') or 'unknown error'}"
        )
    capture_dir = Path(identity_path).resolve().parent
    try:
        _copy_if_needed(Path(identity_path), target)
    finally:
        managed_root = (data_root / "managed").resolve()
        if capture_dir.parent == managed_root:
            shutil.rmtree(capture_dir, ignore_errors=True)


def _ensure_enrollments(
    profile: dict,
    asset_names: tuple[str, ...],
    assets_root: Path,
    data_root: Path,
    database: str,
    *,
    browser_normalized: bool = False,
) -> int:
    created = 0
    existing_hashes = {
        _digest(path)
        for raw_path in identity.profile_reference_audio(profile["id"], database)
        if (path := Path(raw_path)).is_file()
    }
    for asset_name in asset_names:
        source = assets_root / asset_name
        source_hash = _digest(source)
        if not browser_normalized and source_hash in existing_hashes:
            continue
        target_name = (
            f"{Path(asset_name).stem}-browser-normalized.wav"
            if browser_normalized
            else Path(asset_name).name
        )
        target = (
            data_root
            / "demo-bootstrap"
            / "enrollment"
            / profile["display_name"].casefold().replace(" ", "-")
            / target_name
        )
        if browser_normalized:
            _copy_browser_normalized(source, target, data_root)
        else:
            _copy_if_needed(source, target)
        target_hash = _digest(target)
        if target_hash in existing_hashes:
            continue
        result = identity.enroll(
            profile["id"],
            str(target.resolve()),
            capture_device_name="validated fixed rig playback",
            source_type=identity.KIND_INFANT,
            db_path=database,
        )
        if result.get("status") == "enrolled":
            created += 1
            existing_hashes.add(target_hash)
            continue
        if result.get("reason") == "duplicate_audio":
            existing_hashes.add(target_hash)
            continue
        raise PrepareCareDemoError(
            f"could not enroll {source.name} into {profile['display_name']}: "
            f"{result.get('reason') or result.get('status') or 'unknown error'}"
        )
    refreshed = identity.get_profile(profile["id"], database)
    if refreshed.get("status") != "ready" or refreshed.get("enrollments", 0) < 3:
        raise PrepareCareDemoError(
            f"profile {profile['display_name']!r} is not ready after enrollment"
        )
    return created


def _copy_wav_prefix(source: Path, target: Path, seconds: float = 15.0) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(source), "rb") as input_wave:
        parameters = input_wave.getparams()
        frame_count = min(
            input_wave.getnframes(),
            round(input_wave.getframerate() * seconds),
        )
        frames = input_wave.readframes(frame_count)
    with wave.open(str(target), "wb") as output_wave:
        output_wave.setparams(parameters)
        output_wave.writeframes(frames)


def _existing_slots(subject_id: str, database: str) -> set[str]:
    slots = set()
    for episode in store.list_episodes(subject_id, database):
        context = episode.get("context")
        if (
            episode.get("outcome_src") == "seed"
            and isinstance(context, dict)
            and context.get("demo_seed_version") == SEED_VERSION
            and isinstance(context.get("demo_seed_slot"), str)
        ):
            slots.add(context["demo_seed_slot"])
    return slots


def _remove_older_synthetic_memory(subject_id: str, database: str) -> int:
    removed = 0
    for episode in store.list_episodes(subject_id, database):
        context = episode.get("context")
        if (
            episode.get("outcome_src") == "seed"
            and isinstance(context, dict)
            and (
                context.get("demo_seed") is True
                or context.get("synthetic_distinct_recommendation_spike") is True
            )
            and context.get("demo_seed_version") != SEED_VERSION
            and store.delete_episode(episode["id"], database)
        ):
            removed += 1
    return removed


def _seed_distinct_memory(
    profile: dict,
    assets_root: Path,
    data_root: Path,
    database: str,
    now: datetime,
) -> tuple[int, int]:
    subject_id = f"profile-{profile['id']}"
    removed = _remove_older_synthetic_memory(subject_id, database)
    existing = _existing_slots(subject_id, database)
    created = 0
    for group in MEMORY_GROUPS:
        source = assets_root / group["asset"]
        for copy_index in (1, 2):
            slot = f"{group['source']}-{copy_index}"
            if slot in existing:
                continue
            target = (
                data_root
                / "demo-bootstrap"
                / "memory"
                / f"{slot}.wav"
            )
            _copy_wav_prefix(source, target)
            acoustic = fingerprint.compute_windowed(str(target))
            duration = fingerprint.duration_s(str(target))
            if (
                acoustic is None
                or len(acoustic) != fingerprint.DIM
                or duration is None
            ):
                raise PrepareCareDemoError(
                    f"demo memory audio has no usable fingerprint: {source}"
                )
            started_at = (
                now
                - timedelta(days=3 - copy_index)
            ).replace(
                minute=group["minute"] + copy_index - 1,
                second=0,
                microsecond=0,
            )
            episode_id = store.save_episode(
                {
                    "subject_id": subject_id,
                    "started_at": started_at.isoformat(),
                    "duration_s": duration,
                    "audio_path": str(target.resolve()),
                    "fingerprint": acoustic,
                    "transcript": (
                        "SYNTHETIC DEMO MEMORY: "
                        f"{group['evidence']}; caregiver reported that it helped."
                    ),
                    "interventions": [
                        {
                            "order": 1,
                            "action": group["action"],
                            "evidence": group["evidence"],
                        }
                    ],
                    "outcome": group["outcome"],
                    "outcome_src": "seed",
                    "worked": True,
                    "context": {
                        "hour_local": now.hour,
                        "tags": [],
                        "demo_seed": True,
                        "synthetic_demo_memory": True,
                        "demo_seed_version": SEED_VERSION,
                        "demo_seed_slot": slot,
                        "source": group["source"],
                        "source_audio_sha256": _digest(source),
                    },
                },
                database,
            )
            if not episode_id:
                raise PrepareCareDemoError(
                    f"could not save synthetic demo memory {slot}"
                )
            created += 1
    return created, removed


def prepare_care_demo(
    db_path: str | Path | None = None,
    data_root: str | Path | None = None,
    assets_root: str | Path | None = None,
    baseline_db: str | Path | None = None,
    now: datetime | None = None,
) -> dict:
    """Create an idempotent, clean-clone phone demo configuration."""
    database = str(Path(db_path or config.DB_PATH).expanduser().resolve())
    managed_root = Path(data_root or config.AUDIO_DIR).expanduser().resolve()
    fixture_root = Path(assets_root or DEFAULT_ASSETS_ROOT).expanduser().resolve()
    baseline_source = Path(
        baseline_db or DEFAULT_BASELINE_DB
    ).expanduser().resolve()
    demo_now = now or datetime.now().astimezone()
    if demo_now.tzinfo is None:
        raise PrepareCareDemoError("demo time must include a timezone")

    _required_assets(fixture_root)
    store.init_db(database)
    baseline_copied = _ensure_population_baseline(database, baseline_source)

    profiles_created = 0
    enrollments_created = 0
    prepared_profiles = {}
    for name, asset_names in PROFILE_ASSETS.items():
        profile, was_created = _ensure_profile(name, database)
        profiles_created += int(was_created)
        enrollments_created += _ensure_enrollments(
            profile,
            asset_names,
            fixture_root,
            managed_root,
            database,
            browser_normalized=(name == LEARNING_PROFILE),
        )
        prepared_profiles[name] = identity.get_profile(profile["id"], database)

    memories_created, old_memories_removed = _seed_distinct_memory(
        prepared_profiles[DEMO_PROFILE],
        fixture_root,
        managed_root,
        database,
        demo_now,
    )
    return {
        "database": database,
        "data_root": str(managed_root),
        "profiles_created": profiles_created,
        "enrollments_created": enrollments_created,
        "memories_created": memories_created,
        "old_synthetic_memories_removed": old_memories_removed,
        "population_baseline_copied": baseline_copied,
        "profiles": {
            name: {
                "id": profile["id"],
                "status": profile["status"],
                "enrollments": profile["enrollments"],
            }
            for name, profile in prepared_profiles.items()
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Prepare Demo Baby, Learning Baby, and six clearly synthetic "
            "history records for the phone presentation."
        )
    )
    parser.add_argument("--db", default=config.DB_PATH)
    parser.add_argument("--data-root", default=config.AUDIO_DIR)
    parser.add_argument("--assets-root", default=str(DEFAULT_ASSETS_ROOT))
    parser.add_argument("--baseline-db", default=str(DEFAULT_BASELINE_DB))
    args = parser.parse_args(argv)
    try:
        result = prepare_care_demo(
            db_path=args.db,
            data_root=args.data_root,
            assets_root=args.assets_root,
            baseline_db=args.baseline_db,
        )
    except (OSError, PrepareCareDemoError, wave.Error) as exc:
        print(f"care demo setup failed: {exc}", file=sys.stderr)
        return 1
    print(
        "Care demo ready. "
        f"Profiles created: {result['profiles_created']}. "
        f"Enrollments added: {result['enrollments_created']}. "
        f"Memories added: {result['memories_created']}. "
        f"Older synthetic memories replaced: "
        f"{result['old_synthetic_memories_removed']}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
