from __future__ import annotations

import math
import tempfile
import unittest
import wave
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from scripts import prepare_care_demo
from src import (
    audio_ingest,
    careflow,
    care_sessions,
    config,
    fingerprint,
    identity,
    profile_views,
    store,
)


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
        learning_subject_id = f"profile-{profiles['Learning Baby']['id']}"
        self.assertEqual(
            [],
            store.list_episodes(learning_subject_id, str(self.db_path)),
        )

    def test_prepared_learning_profile_matches_browser_normalized_reference(self):
        result = prepare_care_demo.prepare_care_demo(
            db_path=self.db_path,
            data_root=self.data_root,
            assets_root=prepare_care_demo.DEFAULT_ASSETS_ROOT,
            baseline_db=prepare_care_demo.DEFAULT_BASELINE_DB,
            now=datetime.fromisoformat("2026-07-30T15:42:00-04:00"),
        )
        source = (
            prepare_care_demo.DEFAULT_ASSETS_ROOT
            / prepare_care_demo.PROFILE_ASSETS[
                prepare_care_demo.LEARNING_PROFILE
            ][-1]
        )
        ingested = audio_ingest.ingest_audio(
            source.read_bytes(),
            "audio/wav",
            storage_root=self.root / "browser capture",
        )

        self.assertEqual("ready", ingested["status"])
        match = identity.identify(
            ingested["identity_path"],
            kind=identity.KIND_INFANT,
            db_path=str(self.db_path),
            audit=False,
        )
        learning_profile_id = result["profiles"][
            prepare_care_demo.LEARNING_PROFILE
        ]["id"]
        self.assertEqual("match", match["status"])
        self.assertEqual(learning_profile_id, match["profile_id"])
        self.assertEqual(
            prepare_care_demo.LEARNING_PROFILE,
            match["display_name"],
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

    def test_unprepared_profiles_keep_real_history_even_with_reserved_names(self):
        store.init_db(str(self.db_path))
        store.save_baseline(
            config.POPULATION_KEY,
            [0.0] * fingerprint.DIM,
            [1.0] * fingerprint.DIM,
            421,
            str(self.db_path),
        )
        query = self._unit_vector(0)
        for profile_index, name in enumerate(
            (config.CARE_DEMO_PROFILE_NAME, "Learning Baby")
        ):
            profile = identity.create_profile(
                name,
                kind=identity.KIND_INFANT,
                db_path=str(self.db_path),
            )
            subject_id = f"profile-{profile['id']}"
            for copy_index in range(6):
                store.save_episode(
                    {
                        "subject_id": subject_id,
                        "started_at": (
                            f"2026-07-{20 + copy_index:02d}T15:00:00-04:00"
                        ),
                        "duration_s": 3.0,
                        "audio_path": str(
                            self.assets_root
                            / "demo-baby-x4-extended-playback.wav"
                        ),
                        "fingerprint": self._perturbed_vector(
                            query,
                            10 + profile_index * 10 + copy_index,
                            0.08,
                        ),
                        "interventions": [
                            {
                                "order": 1,
                                "action": "ordinary profile action",
                                "evidence": "ordinary profile action",
                            }
                        ],
                        "outcome": "Caregiver said it helped.",
                        "outcome_src": "caregiver",
                        "worked": True,
                        "context": {"hour_local": 15, "tags": []},
                    },
                    str(self.db_path),
                )
            with patch.object(
                careflow.fingerprint,
                "compute_windowed",
                return_value=query,
            ):
                preview = careflow.preview_profile_incident(
                    profile["id"],
                    str(
                        self.assets_root
                        / "demo-baby-x4-extended-playback.wav"
                    ),
                    now="2026-07-30T15:00:00-04:00",
                    db_path=str(self.db_path),
                )

            self.assertEqual("grounded", preview["guidance"]["status"])
            self.assertEqual(6, preview["guidance"]["history_count"])
            self.assertIn(
                "ordinary profile action",
                preview["guidance"]["recommendation"],
            )

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

    def test_completed_visitor_history_cannot_contaminate_controlled_demo_recall(self):
        prepare_care_demo.prepare_care_demo(
            db_path=self.db_path,
            data_root=self.data_root,
            assets_root=self.assets_root,
            baseline_db=self.baseline_db,
            now=datetime.fromisoformat("2026-07-30T15:42:00-04:00"),
        )
        profile = next(
            item
            for item in identity.list_profiles(str(self.db_path))
            if item["display_name"] == "Demo Baby"
        )
        subject_id = f"profile-{profile['id']}"
        query_by_source = {
            "x4": self._unit_vector(0),
            "x7": self._unit_vector(1),
            "x8": self._unit_vector(2),
        }
        expected_by_source = {
            "x4": "offered bottle",
            "x7": "held baby upright",
            "x8": "turned on white noise",
        }
        seed_offsets = iter(range(10, 16))
        for episode in store.list_episodes(subject_id, str(self.db_path)):
            source = episode["context"]["source"]
            store.update_episode(
                episode["id"],
                str(self.db_path),
                fingerprint=self._perturbed_vector(
                    query_by_source[source],
                    next(seed_offsets),
                    0.08,
                ),
            )

        visitor_ids = []
        visitor_offsets = iter(range(20, 26))
        for source, query in query_by_source.items():
            for copy_index in (1, 2):
                visitor_ids.append(
                    store.save_episode(
                        {
                            "subject_id": subject_id,
                            "started_at": (
                                f"2026-07-30T15:{30 + copy_index}:00-04:00"
                            ),
                            "duration_s": 3.0,
                            "audio_path": str(
                                self.assets_root
                                / f"demo-baby-{source}-extended-playback.wav"
                            ),
                            "fingerprint": self._perturbed_vector(
                                query,
                                next(visitor_offsets),
                                0.02,
                            ),
                            "transcript": "Visitor-completed demo incident.",
                            "interventions": [
                                {
                                    "order": 1,
                                    "action": "visitor competing action",
                                    "evidence": "visitor competing action",
                                }
                            ],
                            "outcome": "Visitor said this helped.",
                            "outcome_src": "caregiver",
                            "worked": True,
                            "context": {
                                "hour_local": 15,
                                "tags": [],
                                "care_session_id": 100 + copy_index,
                                "synthetic_demo_memory": (
                                    1 if copy_index == 1 else "true"
                                ),
                            },
                        },
                        str(self.db_path),
                    )
                )

        self.assertEqual(12, len(store.list_episodes(subject_id, str(self.db_path))))
        self.assertTrue(all(visitor_ids))
        history_ids = {
            incident["id"]
            for incident in profile_views.incidents(
                profile["id"],
                str(self.db_path),
                limit=50,
            )["incidents"]
        }
        self.assertTrue(set(visitor_ids) <= history_ids)
        expected_seed_ids = {
            episode["id"]
            for episode in store.list_episodes(subject_id, str(self.db_path))
            if episode["context"].get("synthetic_demo_memory") is True
        }

        for source, expected_action in expected_by_source.items():
            care_session = care_sessions.create(
                profile["id"],
                db_path=str(self.db_path),
            )
            with (
                patch.object(
                    care_sessions.cry_gate,
                    "classify",
                    return_value={
                        "status": "infant_cry_detected",
                        "label": "Infant-cry-like sound detected",
                        "reason_codes": ["infant_cry_evidence_strong"],
                        "analyzed_duration_s": 3.0,
                        "analysis_view_count": 1,
                        "model_version": "test-cry-gate",
                    },
                ),
                patch.object(
                    care_sessions.identity,
                    "identify",
                    return_value={
                        "status": "match",
                        "profile_id": profile["id"],
                        "display_name": profile["display_name"],
                        "kind": identity.KIND_INFANT,
                        "reasons": ["accepted"],
                    },
                ),
                patch.object(
                    care_sessions.audio_duplicate,
                    "signature",
                    return_value=None,
                ),
                patch(
                    "src.careflow.fingerprint.compute_windowed",
                    return_value=query_by_source[source],
                ),
            ):
                direct_preview = careflow.preview_profile_incident(
                    profile["id"],
                    self._ingested(source, 0)["identity_path"],
                    now="2026-07-30T15:42:00-04:00",
                    db_path=str(self.db_path),
                )
                results = [
                    care_sessions.submit_chunk(
                        care_session["id"],
                        sequence,
                        self._ingested(source, sequence),
                        str(self.db_path),
                    )
                    for sequence in range(1, 8)
                ]

            self.assertEqual(6, direct_preview["guidance"]["history_count"])
            decision = results[-1]["session"]["decision"]
            self.assertIsNotNone(decision)
            self.assertEqual("guidance_latched", results[-1]["chunk"]["status"])
            self.assertLessEqual(
                results[-1]["chunk"]["decision_progress"][
                    "analyzed_audio_seconds"
                ],
                45.0,
            )
            self.assertIn(
                expected_action,
                decision["guidance"]["recommendation"].casefold(),
            )
            self.assertTrue(
                set(decision["guidance"]["incident_ids"]) <= expected_seed_ids
            )

    def test_controlled_demo_minimum_gate_ignores_non_seed_history(self):
        prepare_care_demo.prepare_care_demo(
            db_path=self.db_path,
            data_root=self.data_root,
            assets_root=self.assets_root,
            baseline_db=self.baseline_db,
            now=datetime.fromisoformat("2026-07-30T15:42:00-04:00"),
        )
        profile = next(
            item
            for item in identity.list_profiles(str(self.db_path))
            if item["display_name"] == "Demo Baby"
        )
        subject_id = f"profile-{profile['id']}"
        seed = next(
            episode
            for episode in store.list_episodes(subject_id, str(self.db_path))
            if episode["context"].get("synthetic_demo_memory") is True
        )
        store.update_episode(
            seed["id"],
            str(self.db_path),
            context={
                **seed["context"],
                "synthetic_demo_memory": False,
            },
        )
        store.save_episode(
            {
                "subject_id": subject_id,
                "started_at": "2026-07-30T15:50:00-04:00",
                "duration_s": 3.0,
                "audio_path": str(
                    self.assets_root / "demo-baby-x4-extended-playback.wav"
                ),
                "fingerprint": self._unit_vector(0),
                "interventions": [
                    {
                        "order": 1,
                        "action": "visitor action",
                        "evidence": "visitor action",
                    }
                ],
                "outcome": "Visitor said it helped.",
                "outcome_src": "caregiver",
                "worked": True,
                "context": {"hour_local": 15, "tags": []},
            },
            str(self.db_path),
        )

        with patch.object(
            careflow.fingerprint,
            "compute_windowed",
            return_value=self._unit_vector(0),
        ):
            preview = careflow.preview_profile_incident(
                profile["id"],
                str(
                    self.assets_root
                    / "demo-baby-x4-extended-playback.wav"
                ),
                now="2026-07-30T15:50:00-04:00",
                db_path=str(self.db_path),
            )

        self.assertEqual([], preview["scenarios"])
        self.assertEqual("insufficient_history", preview["guidance"]["status"])
        self.assertEqual(5, preview["guidance"]["history_count"])

    @staticmethod
    def _unit_vector(index: int) -> list[float]:
        vector = [0.0] * fingerprint.DIM
        vector[index] = 1.0
        return vector

    @staticmethod
    def _perturbed_vector(
        base: list[float],
        index: int,
        amount: float,
    ) -> list[float]:
        vector = list(base)
        vector[index] = amount
        return vector

    def _ingested(self, source: str, sequence: int) -> dict:
        capture = self.root / "chunks" / source / str(sequence)
        capture.mkdir(parents=True, exist_ok=True)
        payload = f"{source}-{sequence}".encode()
        source_path = capture / "source.webm"
        canonical_path = capture / "canonical.wav"
        identity_path = capture / "identity.wav"
        source_path.write_bytes(b"source-" + payload)
        canonical_path.write_bytes(b"canonical-" + payload)
        identity_path.write_bytes(b"identity-" + payload)
        return {
            "status": "ready",
            "source_path": str(source_path),
            "canonical_path": str(canonical_path),
            "identity_path": str(identity_path),
            "quality": {"duration_s": 3.0},
            "capture": {"source": "test"},
        }


if __name__ == "__main__":
    unittest.main()
