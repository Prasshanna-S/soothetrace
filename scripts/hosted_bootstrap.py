"""Prepare persistent data and model state before a hosted SootheTrace release."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.prepare_care_demo import PrepareCareDemoError, prepare_care_demo
from src import config, cry_gate, encoders, identity, store


def _default_data_root() -> Path:
    configured = os.environ.get("IM_DATA_ROOT")
    if configured:
        return Path(configured).expanduser()
    return Path(config.DB_PATH).expanduser().parent


def _prepare_demo(db_path: str, audio_root: str) -> None:
    prepare_care_demo(db_path=db_path, data_root=audio_root)


def _required_encoders() -> list[str]:
    return sorted(set(identity.ENCODER_FOR_KIND.values()))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Prepare persistent state for a hosted SootheTrace release."
    )
    parser.add_argument("--data-root", default=str(_default_data_root()))
    parser.add_argument("--db", default=os.environ.get("IM_DB_PATH", config.DB_PATH))
    args = parser.parse_args(argv)

    data_root = Path(args.data_root).expanduser().resolve()
    audio_root = data_root / "audio"
    model_root = data_root / "models"
    database = str(Path(args.db).expanduser().resolve())

    try:
        audio_root.mkdir(parents=True, exist_ok=True)
        model_root.mkdir(parents=True, exist_ok=True)
        store.init_db(database)
        baseline = store.get_baseline(config.POPULATION_KEY, database)
        if not baseline:
            print(
                "Hosted bootstrap failed: population baseline is required.",
                file=sys.stderr,
            )
            return 1

        _prepare_demo(database, str(audio_root))
        required_encoders = _required_encoders()
        warmed = encoders.warm(required_encoders)
        unavailable = [name for name in required_encoders if not warmed.get(name)]
        if unavailable:
            print(
                "Hosted bootstrap failed: required encoders are unavailable: "
                + ", ".join(unavailable),
                file=sys.stderr,
            )
            return 1
        if not cry_gate.warm():
            print(
                "Hosted bootstrap failed: cry detector is unavailable.",
                file=sys.stderr,
            )
            return 1
    except (OSError, PrepareCareDemoError) as exc:
        print(f"Hosted bootstrap failed: {exc}", file=sys.stderr)
        return 1

    print(f"Hosted bootstrap ready at {data_root}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
