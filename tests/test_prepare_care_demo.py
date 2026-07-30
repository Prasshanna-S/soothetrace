from __future__ import annotations

import math
import tempfile
import unittest
import wave
from datetime import datetime
from pathlib import Path

from scripts import prepare_care_demo
from src import config, fingerprint, identity, store


def _write_tone(path: Path, frequency: float, seconds: float = 15.0) -> None:
    sample_rate = 16_000
    frames = bytearray()
    for index in range(round(sample_rate * seconds)):
        sample = round(
            11_000 * math.sin(2 * math.pi * frequency * index / sample_rate)
        )
        frames.extend(sample.to_bytes(2, "little", signed=True))
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(frames)


class PrepareCareDemoTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="cry memory care demo ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db_path = self.root / "state" / "episodes.db"
        self.data_root = self.root / "managed audio"
        self.assets_root = self.root / "assets"
        self.baseline_db = self.root / "baseline.db"
        store.init_db(str(self.baseline_db))
        store.save_baseline(
            config.POPULATION_KEY,
            [0.0] * fingerprint.DIM,
            [1.0] * fingerprint.DIM,
            421,
            str(self.baseline_db),
        )

        names = (
            "enrollment/demo-baby-x1.wav",
            "enrollment/demo-baby-x2.wav",
            "enrollment/demo-baby-x3.wav",
            "enrollment/learning-baby-y1.wav",
            "enrollment/learning-baby-y2.wav",
            "enrollment/learning-baby-y4.wav",
            "demo-baby-x4-extended-playback.wav",
            "demo-baby-x7-extended-playback.wav",
            "demo-baby-x8-extended-playback.wav",
        )
        for index, name in enumerate(names):
            _write_tone(self.assets_root / name, 230.0 + index * 47.0)

    def test_prepares_two_ready_profiles_and_six_distinct_demo_memories(self):
        result = prepare_care_demo.prepare_care_demo(
            db_path=self.db_path,
            data_root=self.data_root,
            assets_root=self.assets_root,
            baseline_db=self.baseline_db,
            now=datetime.fromisoformat("2026-07-30T15:42:00-04:00"),
        )

        self.assertEqual(2, result["profiles_created"])
        self.assertEqual(6, result["enrollments_created"])
        self.assertEqual(6, result["memories_created"])
        profiles = {
            item["display_name"]: item
            for item in identity.list_profiles(str(self.db_path))
        }
        self.assertEqual({"Demo Baby", "Learning Baby"}, set(profiles))
        self.assertEqual("ready", profiles["Demo Baby"]["status"])
        self.assertEqual("ready", profiles["Learning Baby"]["status"])
        self.assertEqual(3, profiles["Demo Baby"]["enrollments"])
        self.assertEqual(3, profiles["Learning Baby"]["enrollments"])

        subject_id = f"profile-{profiles['Demo Baby']['id']}"
        memories = store.list_episodes(subject_id, str(self.db_path))
        self.assertEqual(6, len(memories))
        by_source = {}
        for memory in memories:
            context = memory["context"]
            self.assertIs(context["synthetic_demo_memory"], True)
            self.assertEqual(
                prepare_care_demo.SEED_VERSION,
                context["demo_seed_version"],
            )
            self.assertEqual(15, context["hour_local"])
            self.assertEqual([], context["tags"])
            self.assertEqual("seed", memory["outcome_src"])
            self.assertIs(memory["worked"], True)
            self.assertEqual(fingerprint.DIM, len(memory["fingerprint"]))
            by_source.setdefault(context["source"], []).append(memory)
        self.assertEqual({"x4", "x7", "x8"}, set(by_source))
        self.assertEqual([2, 2, 2], sorted(map(len, by_source.values())))
        self.assertEqual(
            {"offered bottle"},
            {
                item["interventions"][0]["action"]
                for item in by_source["x4"]
            },
        )
        self.assertEqual(
            {"held baby upright"},
            {
                item["interventions"][0]["action"]
                for item in by_source["x7"]
            },
        )
        self.assertEqual(
            {"turned on white noise"},
            {
                item["interventions"][0]["action"]
                for item in by_source["x8"]
            },
        )
        self.assertEqual(
            421,
            store.get_baseline(config.POPULATION_KEY, str(self.db_path))["n"],
        )

    def test_rerun_is_idempotent_and_preserves_real_history(self):
        first = prepare_care_demo.prepare_care_demo(
            db_path=self.db_path,
            data_root=self.data_root,
            assets_root=self.assets_root,
            baseline_db=self.baseline_db,
            now=datetime.fromisoformat("2026-07-30T15:42:00-04:00"),
        )
        demo_profile = next(
            item
            for item in identity.list_profiles(str(self.db_path))
            if item["display_name"] == "Demo Baby"
        )
        real_id = store.save_episode(
            {
                "subject_id": f"profile-{demo_profile['id']}",
                "started_at": "2026-07-29T11:00:00-04:00",
                "duration_s": 15.0,
                "audio_path": str(
                    self.assets_root / "demo-baby-x4-extended-playback.wav"
                ),
                "fingerprint": [0.25] * fingerprint.DIM,
                "transcript": "Caregiver recorded incident.",
                "interventions": [
                    {
                        "order": 1,
                        "action": "held baby",
                        "evidence": "held baby",
                    }
                ],
                "outcome": "Caregiver report.",
                "outcome_src": "caregiver",
                "worked": True,
                "context": {"hour_local": 11, "tags": []},
            },
            str(self.db_path),
        )

        second = prepare_care_demo.prepare_care_demo(
            db_path=self.db_path,
            data_root=self.data_root,
            assets_root=self.assets_root,
            baseline_db=self.baseline_db,
            now=datetime.fromisoformat("2026-07-30T16:10:00-04:00"),
        )

        self.assertEqual(2, first["profiles_created"])
        self.assertEqual(0, second["profiles_created"])
        self.assertEqual(0, second["enrollments_created"])
        self.assertEqual(0, second["memories_created"])
        self.assertIsNotNone(store.get_episode(real_id, str(self.db_path)))
        rows = store.list_episodes(
            f"profile-{demo_profile['id']}",
            str(self.db_path),
        )
        self.assertEqual(7, len(rows))

    def test_replaces_only_older_synthetic_demo_seed_rows(self):
        profile = identity.create_profile(
            "Demo Baby",
            kind=identity.KIND_INFANT,
            db_path=str(self.db_path),
        )
        old_id = store.save_episode(
            {
                "subject_id": f"profile-{profile['id']}",
                "started_at": "2026-07-20T18:45:00-04:00",
                "duration_s": 15.0,
                "audio_path": str(
                    self.assets_root / "demo-baby-x4-extended-playback.wav"
                ),
                "fingerprint": [0.1] * fingerprint.DIM,
                "transcript": "SYNTHETIC DEMO MEMORY: old seed",
                "interventions": [
                    {
                        "order": 1,
                        "action": "old action",
                        "evidence": "old action",
                    }
                ],
                "outcome": "Synthetic demo outcome: old seed.",
                "outcome_src": "seed",
                "worked": True,
                "context": {
                    "demo_seed": True,
                    "demo_seed_version": "profile-care-memory-v1",
                    "hour_local": 18,
                    "tags": [],
                },
            },
            str(self.db_path),
        )

        result = prepare_care_demo.prepare_care_demo(
            db_path=self.db_path,
            data_root=self.data_root,
            assets_root=self.assets_root,
            baseline_db=self.baseline_db,
            now=datetime.fromisoformat("2026-07-30T15:42:00-04:00"),
        )

        self.assertEqual(1, result["old_synthetic_memories_removed"])
        self.assertIsNone(store.get_episode(old_id, str(self.db_path)))


if __name__ == "__main__":
    unittest.main()
