import json
import unittest
from unittest.mock import patch

import numpy as np

from tests.test_product_http_api import ProductServer, _wav_bytes


class EndToEndPhoneLoopTests(unittest.TestCase):
    def setUp(self):
        self.product = ProductServer()
        self.addCleanup(self.product.close)

    def test_phone_to_laptop_identity_memory_guidance_and_playback_loop(self):
        from src import careflow, config, http_api, store

        baby_a = self.product.json(
            "POST",
            "/api/profiles",
            {"display_name": "Baby A", "kind": "infant"},
        )["json"]["profile"]
        self.product.json(
            "POST",
            "/api/profiles",
            {"display_name": "Baby B", "kind": "infant"},
        )

        evidence_dir = self.product.data_root / "managed" / "seed-evidence"
        evidence_dir.mkdir(parents=True)
        evidence_path = evidence_dir / "canonical.wav"
        evidence_path.write_bytes(_wav_bytes())
        subject_id = f"profile-{baby_a['id']}"
        query_fingerprint = np.zeros(87, dtype=np.float64)
        query_fingerprint[0] = 1.0
        prior_ids = []
        for index in range(6):
            prior = query_fingerprint.copy()
            prior[index + 1] = 0.04 + index * 0.01
            prior_ids.append(
                store.save_episode(
                    {
                        "subject_id": subject_id,
                        "started_at": f"2026-07-{20 + index:02d}T03:00:00-04:00",
                        "duration_s": 9.0,
                        "audio_path": str(evidence_path),
                        "fingerprint": prior.tolist(),
                        "transcript": "I walked around the room.",
                        "interventions": [
                            {
                                "order": 1,
                                "action": "walked around the room",
                                "evidence": "walked around the room",
                            }
                        ],
                        "outcome": "The caregiver said the baby settled.",
                        "outcome_src": "caregiver",
                        "worked": True,
                        "context": {"hour_local": 3, "tags": ["overtired"]},
                    },
                    self.product.db_path,
                )
            )
        store.save_baseline(
            config.POPULATION_KEY,
            np.zeros(87),
            np.ones(87),
            421,
            self.product.db_path,
        )

        attempt = self.product.json(
            "POST",
            "/api/identity/attempts",
            {"kind": "infant"},
        )["json"]["attempt"]
        match = {
            "status": "match",
            "profile_id": baby_a["id"],
            "display_name": "Baby A",
            "kind": "infant",
            "band": "weak",
            "score": 0.92,
            "margin": 0.14,
            "support": {"enrollment_id": 1, "audio_path": "managed"},
            "reasons": ["acoustically_consistent_with_enrolled_profile"],
            "candidates": [
                {
                    "profile_id": baby_a["id"],
                    "display_name": "Baby A",
                    "kind": "infant",
                    "score": 0.92,
                }
            ],
            "quality": {
                "mean_db": -24.0,
                "peak_db": -8.0,
                "voiced_fraction": 0.75,
                "duration_s": 1.0,
            },
            "pool_size": 2,
            "versions": {
                "encoder": "mfcc87-v1",
                "calibration": "test",
                "aggregation": "mean-whole-file-v1",
                "cohort": None,
            },
        }
        audio = _wav_bytes()
        with patch.object(http_api.identity, "identify", return_value=match):
            identified = self.product.request(
                "POST",
                f"/api/identity/attempts/{attempt['id']}/captures",
                audio,
                {"Content-Type": "audio/wav", "Content-Length": str(len(audio))},
            )
        identity_payload = json.loads(identified["body"].decode("utf-8"))["identity"]
        self.assertEqual("match", identity_payload["status"])
        self.assertEqual("Baby A", identity_payload["profile"]["display_name"])

        with (
            patch.object(
                careflow.fingerprint,
                "compute_windowed",
                return_value=query_fingerprint.tolist(),
            ),
            patch.object(careflow.session.fingerprint, "duration_s", return_value=8.0),
            patch.object(
                careflow.session.speech,
                "transcribe",
                return_value="I picked the baby up and walked around the room.",
            ),
            patch.object(
                careflow.session.speech,
                "extract_interventions",
                return_value=[
                    {
                        "order": 1,
                        "action": "walked around the room",
                        "evidence": "walked around the room",
                    }
                ],
            ),
        ):
            completed = self.product.json(
                "POST",
                f"/api/incidents/{attempt['id']}/complete",
                {
                    "caregiver_answer": "Walking worked and the baby settled.",
                    "tags": ["overtired"],
                },
            )

        self.assertEqual(200, completed["status"])
        result = completed["json"]
        self.assertEqual("complete", result["status"])
        self.assertEqual(baby_a["id"], result["identity"]["profile_id"])
        self.assertEqual("grounded", result["guidance"]["status"])
        self.assertEqual("walked around the room", result["guidance"]["action"])
        self.assertTrue(set(result["guidance"]["incident_ids"]).issubset(set(prior_ids)))
        self.assertEqual(7, len(store.list_episodes(subject_id, self.product.db_path)))
        self.assertEqual(
            attempt["id"],
            result["episode"]["context"]["identity_attempt_id"],
        )

        public_json = json.dumps(result)
        self.assertNotIn("similarity", public_json)
        self.assertNotIn("rank_score", public_json)
        self.assertNotIn("weights_used", public_json)
        self.assertNotIn("fingerprint", public_json)
        self.assertNotIn("audio_path", public_json)
        evidence_id = result["guidance"]["incident_ids"][0]
        self.assertEqual(
            f"/api/audio/episodes/{evidence_id}",
            result["scenarios"][0]["audio_url"],
        )
        playback = self.product.request(
            "GET",
            f"/api/audio/episodes/{evidence_id}",
        )
        self.assertEqual(200, playback["status"])
        self.assertEqual(evidence_path.read_bytes(), playback["body"])
