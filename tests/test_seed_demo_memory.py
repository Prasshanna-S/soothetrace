from __future__ import annotations

import hashlib
import io
import math
import sqlite3
import struct
import tempfile
import unittest
import wave
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from scripts import seed_demo_memory
from src import encoders, fingerprint, identity, store


TARGET_NAMES = ("Baby 1", "Baby 2", "Baby 3")


def _write_tone(path: Path, frequency: float, seconds: float = 0.65) -> None:
    sample_rate = 16_000
    frames = bytearray()
    for index in range(round(sample_rate * seconds)):
        sample = round(12_000 * math.sin(2 * math.pi * frequency * index / sample_rate))
        frames.extend(struct.pack("<h", sample))
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(frames)


class SeedDemoMemoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="cry memory seed tests ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db_path = self.root / "database state" / "episodes.db"
        self.data_root = self.root / "managed demo audio"
        self.reference_root = self.root / "enrollment references"
        store.init_db(str(self.db_path))

        self.profiles = {}
        self.references = {}
        for profile_index, name in enumerate(TARGET_NAMES):
            profile = identity.create_profile(
                name,
                kind=identity.KIND_INFANT,
                db_path=str(self.db_path),
            )
            self.profiles[name] = profile
            paths = []
            for reference_index in range(3):
                path = (
                    self.reference_root
                    / f"profile {profile_index + 1}"
                    / f"reference {reference_index + 1}.wav"
                )
                _write_tone(
                    path,
                    frequency=330.0 + profile_index * 90.0 + reference_index * 35.0,
                )
                paths.append(path)
                self._insert_enrollment(profile["id"], path, reference_index)
            self.references[name] = paths

    def _insert_enrollment(
        self,
        profile_id: int,
        audio_path: Path,
        reference_index: int,
    ) -> None:
        digest = hashlib.sha256(audio_path.read_bytes()).hexdigest()
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                "INSERT INTO enrollment ("
                "profile_id, audio_path, audio_sha256, captured_at, duration_s, "
                "capture_device_name, capture_quality, source_type, encoder_version, "
                "embedding"
                ") VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    profile_id,
                    str(audio_path),
                    digest,
                    f"2026-07-{reference_index + 1:02d}T12:00:00+00:00",
                    0.65,
                    "synthetic test fixture",
                    "{}",
                    identity.KIND_INFANT,
                    encoders.MFCC87,
                    b"\0" * (fingerprint.DIM * 4),
                ),
            )
            connection.execute(
                "UPDATE profile SET status='ready' WHERE id=?",
                (profile_id,),
            )

    @staticmethod
    def _seed_rows(rows: list[dict]) -> list[dict]:
        return [
            row
            for row in rows
            if row.get("context", {}).get("demo_seed") is True
        ]

    def test_cli_seeds_six_real_synthetic_managed_episodes_per_profile(self):
        output = io.StringIO()
        with redirect_stdout(output):
            status = seed_demo_memory.main(
                [
                    "--db",
                    str(self.db_path),
                    "--data-root",
                    str(self.data_root),
                ]
            )

        self.assertEqual(0, status)
        self.assertIn("18 synthetic demo-memory episodes created", output.getvalue())
        all_audio_paths = set()
        for name in TARGET_NAMES:
            profile = self.profiles[name]
            subject_id = f"profile-{profile['id']}"
            rows = self._seed_rows(store.list_episodes(subject_id, str(self.db_path)))
            self.assertEqual(6, len(rows))

            profile_paths = {row["audio_path"] for row in rows}
            self.assertEqual(6, len(profile_paths))
            self.assertTrue(all_audio_paths.isdisjoint(profile_paths))
            all_audio_paths.update(profile_paths)

            for row in rows:
                managed_path = Path(row["audio_path"]).resolve()
                self.assertTrue(managed_path.is_relative_to(self.data_root.resolve()))
                self.assertTrue(managed_path.is_file())
                self.assertEqual(".wav", managed_path.suffix.casefold())
                self.assertEqual("seed", row["outcome_src"])
                self.assertIsInstance(row["worked"], bool)
                self.assertTrue(row["outcome"])
                self.assertEqual(fingerprint.DIM, len(row["fingerprint"]))
                self.assertTrue(row["interventions"])
                self.assertTrue(row["transcript"].startswith("SYNTHETIC DEMO MEMORY:"))

                context = row["context"]
                self.assertIs(context["demo_seed"], True)
                self.assertEqual(
                    seed_demo_memory.SEED_VERSION,
                    context["demo_seed_version"],
                )
                self.assertIn(context["demo_seed_slot"], range(1, 7))
                self.assertIn(
                    context["demo_seed_source_enrollment_index"],
                    range(1, 4),
                )
                self.assertTrue(context["tags"])
                self.assertIsInstance(context["hour_local"], int)
                started_at = datetime.fromisoformat(row["started_at"])
                self.assertIsNotNone(started_at.utcoffset())
                self.assertLess(started_at, datetime.now(timezone.utc).astimezone())

                source = self.references[name][
                    context["demo_seed_source_enrollment_index"] - 1
                ]
                self.assertEqual(source.read_bytes(), managed_path.read_bytes())

            sample = rows[0]
            expected = fingerprint.compute_windowed(sample["audio_path"])
            self.assertIsNotNone(expected)
            self.assertEqual(fingerprint.DIM, len(expected))
            self.assertLess(
                max(
                    abs(actual - wanted)
                    for actual, wanted in zip(sample["fingerprint"], expected)
                ),
                1e-5,
            )

    def test_rerun_is_idempotent(self):
        first = seed_demo_memory.seed_demo_memory(
            db_path=self.db_path,
            data_root=self.data_root,
        )
        before = {
            name: {
                row["id"]
                for row in self._seed_rows(
                    store.list_episodes(
                        f"profile-{self.profiles[name]['id']}",
                        str(self.db_path),
                    )
                )
            }
            for name in TARGET_NAMES
        }

        second = seed_demo_memory.seed_demo_memory(
            db_path=self.db_path,
            data_root=self.data_root,
        )

        self.assertEqual(18, first["created"])
        self.assertEqual(0, first["existing"])
        self.assertEqual(0, second["created"])
        self.assertEqual(18, second["existing"])
        for name in TARGET_NAMES:
            rows = self._seed_rows(
                store.list_episodes(
                    f"profile-{self.profiles[name]['id']}",
                    str(self.db_path),
                )
            )
            self.assertEqual(6, len(rows))
            self.assertEqual(before[name], {row["id"] for row in rows})

    def test_preserves_existing_non_seed_history(self):
        profile = self.profiles["Baby 1"]
        subject_id = f"profile-{profile['id']}"
        original_id = store.save_episode(
            {
                "subject_id": subject_id,
                "started_at": "2026-06-01T09:15:00+00:00",
                "duration_s": 0.65,
                "audio_path": str(self.references["Baby 1"][0]),
                "fingerprint": [0.25] * fingerprint.DIM,
                "transcript": "Real caregiver history.",
                "interventions": [
                    {
                        "order": 1,
                        "action": "held baby",
                        "evidence": "Real caregiver history.",
                    }
                ],
                "outcome": "Caregiver-recorded outcome.",
                "outcome_src": "caregiver",
                "worked": True,
                "context": {"hour_local": 9, "tags": ["caregiver note"]},
            },
            str(self.db_path),
        )

        seed_demo_memory.seed_demo_memory(
            db_path=self.db_path,
            data_root=self.data_root,
        )

        rows = store.list_episodes(subject_id, str(self.db_path))
        self.assertEqual(7, len(rows))
        preserved = store.get_episode(original_id, str(self.db_path))
        self.assertEqual("caregiver", preserved["outcome_src"])
        self.assertEqual("Caregiver-recorded outcome.", preserved["outcome"])
        self.assertEqual({"hour_local": 9, "tags": ["caregiver note"]}, preserved["context"])
        self.assertEqual(6, len(self._seed_rows(rows)))

    def test_prefers_canonical_wav_next_to_ingest_identity_reference(self):
        profile = self.profiles["Baby 1"]
        capture_dir = self.reference_root / "profile 1" / "ingest capture"
        identity_path = capture_dir / "identity.wav"
        canonical_path = capture_dir / "canonical.wav"
        _write_tone(identity_path, frequency=730.0)
        _write_tone(canonical_path, frequency=185.0)
        with sqlite3.connect(self.db_path) as connection:
            enrollment_id = connection.execute(
                "SELECT id FROM enrollment WHERE profile_id=? ORDER BY id LIMIT 1",
                (profile["id"],),
            ).fetchone()[0]
            connection.execute(
                "UPDATE enrollment SET audio_path=?, audio_sha256=? WHERE id=?",
                (
                    str(identity_path),
                    hashlib.sha256(identity_path.read_bytes()).hexdigest(),
                    enrollment_id,
                ),
            )

        seed_demo_memory.seed_demo_memory(
            db_path=self.db_path,
            data_root=self.data_root,
        )

        rows = self._seed_rows(
            store.list_episodes(f"profile-{profile['id']}", str(self.db_path))
        )
        canonical_rows = [
            row
            for row in rows
            if row["context"]["demo_seed_source_enrollment_index"] == 1
        ]
        self.assertEqual(2, len(canonical_rows))
        for row in canonical_rows:
            managed_path = Path(row["audio_path"])
            self.assertEqual(canonical_path.read_bytes(), managed_path.read_bytes())
            self.assertNotEqual(identity_path.read_bytes(), managed_path.read_bytes())
            self.assertEqual(
                hashlib.sha256(canonical_path.read_bytes()).hexdigest(),
                row["context"]["demo_seed_source_audio_sha256"],
            )

    def test_removes_copied_audio_when_episode_save_fails(self):
        with patch.object(seed_demo_memory.store, "save_episode", return_value=0):
            with self.assertRaisesRegex(
                seed_demo_memory.SeedDemoError,
                "failed to save synthetic episode 1 for Baby 1",
            ):
                seed_demo_memory.seed_demo_memory(
                    db_path=self.db_path,
                    data_root=self.data_root,
                )

        demo_root = self.data_root / "demo-memory"
        copied_wavs = list(demo_root.rglob("*.wav")) if demo_root.exists() else []
        self.assertEqual([], copied_wavs)

    def test_requires_three_usable_enrollment_references_before_writing(self):
        profile = self.profiles["Baby 3"]
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                "DELETE FROM enrollment WHERE id=("
                "SELECT id FROM enrollment WHERE profile_id=? ORDER BY id DESC LIMIT 1"
                ")",
                (profile["id"],),
            )

        with self.assertRaisesRegex(
            seed_demo_memory.SeedDemoError,
            "Baby 3.*at least 3",
        ):
            seed_demo_memory.seed_demo_memory(
                db_path=self.db_path,
                data_root=self.data_root,
            )

        for name in TARGET_NAMES:
            subject_id = f"profile-{self.profiles[name]['id']}"
            self.assertEqual(
                [],
                self._seed_rows(store.list_episodes(subject_id, str(self.db_path))),
            )
        self.assertFalse((self.data_root / "demo-memory").exists())


if __name__ == "__main__":
    unittest.main()
