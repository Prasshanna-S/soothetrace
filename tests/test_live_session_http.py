"""HTTP contract tests for incremental live identity sessions."""

from __future__ import annotations

import json
import sqlite3
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.test_product_http_api import ProductServer, _wav_bytes


class LiveSessionHttpTests(unittest.TestCase):
    def setUp(self):
        self.product = ProductServer()
        self.addCleanup(self.product.close)

    @staticmethod
    def _encode(encoder_name, _audio_path):
        from src import encoders

        dimensions = encoders.dim(encoder_name)
        return [1.0] + [0.0] * (dimensions - 1)

    def _create(self):
        response = self.product.json(
            "POST",
            "/api/live-sessions",
            {"kind": "human_imitation"},
        )
        self.assertEqual(201, response["status"], response["body"])
        return response

    def _observe(self, session_id, audio=None, headers=None):
        body = audio if audio is not None else _wav_bytes()
        return self.product.request(
            "POST",
            f"/api/live-sessions/{session_id}/observations",
            body,
            {
                "Content-Type": "audio/wav",
                "Content-Length": str(len(body)),
                "X-Capture-Source": "upload",
                **(headers or {}),
            },
        )

    def _assert_public(self, value):
        forbidden_fragments = (
            "path",
            "sha",
            "digest",
            "embedding",
            "score",
            "margin",
            "similarity",
            "confidence",
            "quality",
            "candidate",
            "expected",
        )
        if isinstance(value, dict):
            for key, child in value.items():
                lowered = key.casefold()
                self.assertFalse(
                    any(fragment in lowered for fragment in forbidden_fragments),
                    f"private live-session key leaked: {key}",
                )
                self._assert_public(child)
        elif isinstance(value, list):
            for child in value:
                self._assert_public(child)

    def _assert_live_scalar_types(self, payload):
        def optional_int(container, key):
            if key in container:
                self.assertIs(type(container[key]), int, key)

        def optional_text(container, key):
            if key in container:
                self.assertTrue(
                    container[key] is None or type(container[key]) is str,
                    key,
                )

        def participant_types(participant):
            self.assertIs(type(participant), dict)
            self.assertLessEqual(
                set(participant),
                {
                    "id",
                    "profile_id",
                    "display_name",
                    "state",
                    "support_count",
                    "created_at",
                    "established_at",
                },
            )
            for key in ("id", "profile_id", "support_count"):
                optional_int(participant, key)
            for key in (
                "display_name",
                "state",
                "created_at",
                "established_at",
            ):
                optional_text(participant, key)

        def observation_types(observation):
            self.assertIs(type(observation), dict)
            self.assertLessEqual(
                set(observation),
                {
                    "id",
                    "sequence",
                    "created_at",
                    "source_type",
                    "status",
                    "participant_id",
                    "closest_participant_id",
                    "participant",
                    "closest_participant",
                    "reinforced",
                    "reason_codes",
                    "playback_url",
                },
            )
            for key in (
                "id",
                "sequence",
                "participant_id",
                "closest_participant_id",
            ):
                optional_int(observation, key)
            for key in (
                "created_at",
                "source_type",
                "status",
                "playback_url",
            ):
                optional_text(observation, key)
            if "reinforced" in observation:
                self.assertIs(type(observation["reinforced"]), bool)
            self.assertIs(type(observation["reason_codes"]), list)
            self.assertTrue(
                all(type(reason) is str for reason in observation["reason_codes"])
            )
            for key in ("participant", "closest_participant"):
                if key in observation and observation[key] is not None:
                    participant_types(observation[key])

        self.assertEqual(
            {"session", "observation", "classification"},
            set(payload),
        )
        session = payload["session"]
        self.assertIs(type(session), dict)
        self.assertLessEqual(
            set(session),
            {
                "id",
                "kind",
                "status",
                "created_at",
                "completed_at",
                "participants",
                "observations",
            },
        )
        optional_int(session, "id")
        for key in ("kind", "status", "created_at", "completed_at"):
            optional_text(session, key)
        self.assertIs(type(session["participants"]), list)
        self.assertIs(type(session["observations"]), list)
        for participant in session["participants"]:
            participant_types(participant)
        for observation in session["observations"]:
            observation_types(observation)

        observation = payload["observation"]
        if observation is not None:
            observation_types(observation)

        classification = payload["classification"]
        self.assertIs(type(classification), dict)
        self.assertLessEqual(
            set(classification),
            {"status", "participant", "reinforced", "reason_codes"},
        )
        optional_text(classification, "status")
        if "reinforced" in classification:
            self.assertIs(type(classification["reinforced"]), bool)
        self.assertIs(type(classification["reason_codes"]), list)
        self.assertTrue(
            all(type(reason) is str for reason in classification["reason_codes"])
        )
        if (
            "participant" in classification
            and classification["participant"] is not None
        ):
            participant_types(classification["participant"])

    def test_create_observe_load_complete_and_reject_late_observation(self):
        from src import http_api

        created = self._create()
        session_id = created["json"]["session"]["id"]

        with patch.object(http_api.encoders, "encode", side_effect=self._encode):
            observed = self._observe(session_id)
        loaded = self.product.request("GET", f"/api/live-sessions/{session_id}")
        completed = self.product.json(
            "POST",
            f"/api/live-sessions/{session_id}/complete",
        )
        late = self._observe(session_id, _wav_bytes(660.0))

        self.assertEqual("open", created["json"]["session"]["status"])
        self.assertEqual(201, observed["status"], observed["body"])
        self.assertEqual(
            "provisional_created",
            observed["json"]["classification"]["status"],
        )
        self.assertEqual(
            "Person A",
            observed["json"]["classification"]["participant"]["display_name"],
        )
        self.assertEqual(
            "upload",
            observed["json"]["observation"]["source_type"],
        )
        self.assertEqual(200, loaded["status"], loaded["body"])
        self.assertEqual(
            [observed["json"]["observation"]["id"]],
            [
                observation["id"]
                for observation in loaded["json"]["session"]["observations"]
            ],
        )
        self.assertEqual(200, completed["status"], completed["body"])
        self.assertEqual("completed", completed["json"]["session"]["status"])
        self.assertEqual(409, late["status"], late["body"])
        self.assertEqual(
            "session_completed",
            late["json"]["classification"]["status"],
        )
        self._assert_public(created["json"])
        self._assert_public(observed["json"])
        self._assert_public(loaded["json"])
        self._assert_public(completed["json"])
        self._assert_public(late["json"])

    def test_duplicate_observation_is_accepted_without_reinforcement(self):
        from src import http_api

        session_id = self._create()["json"]["session"]["id"]
        audio = _wav_bytes()
        with patch.object(http_api.encoders, "encode", side_effect=self._encode):
            first = self._observe(session_id, audio)
            duplicate = self._observe(session_id, audio)

        self.assertEqual(201, first["status"], first["body"])
        self.assertEqual(201, duplicate["status"], duplicate["body"])
        self.assertEqual("duplicate", duplicate["json"]["classification"]["status"])
        self.assertFalse(duplicate["json"]["classification"]["reinforced"])
        self.assertEqual(2, len(duplicate["json"]["session"]["observations"]))
        self.assertEqual(
            "provisional",
            duplicate["json"]["classification"]["participant"]["state"],
        )
        self._assert_public(duplicate["json"])

    def test_invalid_audio_is_422_and_does_not_expose_ingest_evidence(self):
        session_id = self._create()["json"]["session"]["id"]

        invalid = self._observe(session_id, b"not a wav")

        self.assertEqual(422, invalid["status"], invalid["body"])
        self.assertEqual("invalid", invalid["json"]["classification"]["status"])
        self.assertEqual([], invalid["json"]["session"]["observations"])
        self.assertIsNone(invalid["json"]["observation"])
        self.assertIn(
            "decode_failed",
            invalid["json"]["classification"]["reason_codes"],
        )
        self.assertNotIn(str(self.product.data_root), json.dumps(invalid["json"]))
        self._assert_public(invalid["json"])

    def test_acoustic_invalid_result_is_422(self):
        from src import http_api

        session = self._create()["json"]["session"]
        service_result = {
            "session": session,
            "observation": None,
            "classification": {
                "status": "invalid",
                "participant": None,
                "reinforced": False,
                "reason_codes": ["no_usable_voiced_audio"],
            },
        }
        with patch.object(
            http_api.live_sessions,
            "submit_observation",
            return_value=service_result,
        ):
            response = self._observe(session["id"])

        self.assertEqual(422, response["status"], response["body"])
        self.assertEqual(
            ["no_usable_voiced_audio"],
            response["json"]["classification"]["reason_codes"],
        )

    def test_observation_route_passes_managed_paths_and_capture_metadata(self):
        from src import http_api

        session = self._create()["json"]["session"]
        captured = {}
        service_result = {
            "session": {
                **session,
                "expected_identity_label": "must not leak",
            },
            "observation": {
                "id": 77,
                "sequence": 1,
                "created_at": session["created_at"],
                "source_type": "microphone",
                "status": "provisional_created",
                "participant_id": 8,
                "closest_participant_id": None,
                "participant": {
                    "id": 8,
                    "profile_id": 9,
                    "display_name": "Person A",
                    "state": "provisional",
                    "support_count": 1,
                    "created_at": session["created_at"],
                    "established_at": None,
                },
                "closest_participant": None,
                "reinforced": False,
                "reason_codes": ["new_participant"],
                "playback_url": "/private/played.wav",
                "source_audio_path": "/private/source.wav",
                "audio_sha256": "secret",
            },
            "classification": {
                "status": "provisional_created",
                "participant": {
                    "id": 8,
                    "profile_id": 9,
                    "display_name": "Person A",
                    "state": "provisional",
                    "support_count": 1,
                    "created_at": session["created_at"],
                    "established_at": None,
                },
                "reinforced": False,
                "reason_codes": ["new_participant"],
                "score": 0.999,
                "expected_person": "secret",
            },
        }

        def submit(session_id, audio_path, capture_metadata=None, db_path=None):
            captured.update(
                {
                    "session_id": session_id,
                    "audio_path": audio_path,
                    "capture_metadata": capture_metadata,
                    "db_path": db_path,
                }
            )
            return service_result

        with patch.object(
            http_api.live_sessions,
            "submit_observation",
            side_effect=submit,
        ):
            response = self._observe(
                session["id"],
                headers={
                    "X-Capture-Source": "microphone",
                    "X-Capture-Device": "iPhone Safari",
                    "User-Agent": "Live Session Test",
                },
            )

        self.assertEqual(201, response["status"], response["body"])
        metadata = captured["capture_metadata"]
        self.assertEqual(session["id"], captured["session_id"])
        self.assertEqual(self.product.db_path, captured["db_path"])
        self.assertEqual(metadata["identity_path"], captured["audio_path"])
        self.assertEqual("microphone", metadata["capture_source"])
        self.assertEqual("iPhone Safari", metadata["capture_device_name"])
        self.assertEqual("Live Session Test", metadata["user_agent"])
        for key in ("source_path", "canonical_path", "identity_path"):
            managed = Path(metadata[key])
            self.assertTrue(managed.is_file())
            self.assertIn((self.product.data_root / "managed").resolve(), managed.parents)
        self.assertEqual(
            "/api/audio/live-observations/77",
            response["json"]["observation"]["playback_url"],
        )
        self._assert_public(response["json"])

    def test_public_live_response_rejects_nested_values_in_every_scalar_slot(self):
        from src import http_api

        session_id = self._create()["json"]["session"]["id"]
        forbidden_values = {
            "Alice",
            "/private/leak.wav",
        }
        for poison in (
            {
                "score": 0.99,
                "expected_person": "Alice",
                "source_path": "/private/leak.wav",
            },
            [
                {
                    "score": 0.99,
                    "expected_person": "Alice",
                    "source_path": "/private/leak.wav",
                }
            ],
        ):
            with self.subTest(poison_type=type(poison).__name__):
                participant = {
                    "id": poison,
                    "profile_id": poison,
                    "display_name": poison,
                    "state": poison,
                    "support_count": poison,
                    "created_at": poison,
                    "established_at": poison,
                }
                observation = {
                    "id": poison,
                    "sequence": poison,
                    "created_at": poison,
                    "source_type": poison,
                    "status": poison,
                    "participant_id": poison,
                    "closest_participant_id": poison,
                    "participant": participant,
                    "closest_participant": participant,
                    "reinforced": poison,
                    "reason_codes": [poison],
                    "playback_url": poison,
                }
                service_result = {
                    "session": {
                        "id": poison,
                        "kind": poison,
                        "status": poison,
                        "created_at": poison,
                        "completed_at": poison,
                        "participants": [participant],
                        "observations": [observation],
                    },
                    "observation": observation,
                    "classification": {
                        "status": poison,
                        "participant": participant,
                        "reinforced": poison,
                        "reason_codes": [poison],
                    },
                }
                with patch.object(
                    http_api.live_sessions,
                    "submit_observation",
                    return_value=service_result,
                ):
                    response = self._observe(session_id)

                self.assertEqual(201, response["status"], response["body"])
                self._assert_live_scalar_types(response["json"])
                self._assert_public(response["json"])
                encoded = json.dumps(response["json"])
                for forbidden in forbidden_values:
                    self.assertNotIn(forbidden, encoded)

    def test_observation_playback_uses_only_managed_canonical_audio(self):
        from src import http_api

        session_id = self._create()["json"]["session"]["id"]
        with patch.object(http_api.encoders, "encode", side_effect=self._encode):
            observed = self._observe(session_id)
        observation = observed["json"]["observation"]
        canonical_path = Path(
            http_api.live_sessions.observation_audio_path(
                observation["id"],
                self.product.db_path,
            )
        )

        playback = self.product.request("GET", observation["playback_url"])
        with sqlite3.connect(self.product.db_path) as connection:
            connection.execute(
                "UPDATE live_identity_observation "
                "SET canonical_audio_path=NULL WHERE id=?",
                (observation["id"],),
            )
        identity_fallback = self.product.request(
            "GET",
            observation["playback_url"],
        )
        outside = Path(self.product.temp.name) / "outside.wav"
        outside.write_bytes(_wav_bytes())
        with patch.object(
            http_api.live_sessions,
            "observation_audio_path",
            return_value=str(outside),
        ):
            denied = self.product.request(
                "GET",
                "/api/audio/live-observations/999",
            )

        self.assertEqual(200, playback["status"], playback["body"])
        self.assertEqual("audio/wav", playback["headers"]["content-type"])
        self.assertEqual("canonical.wav", canonical_path.name)
        self.assertEqual(canonical_path.read_bytes(), playback["body"])
        self.assertEqual(404, identity_fallback["status"], identity_fallback["body"])
        self.assertEqual(404, denied["status"], denied["body"])

    def test_missing_session_and_observation_routes_return_404(self):
        missing_get = self.product.request("GET", "/api/live-sessions/999")
        missing_post = self._observe(999)
        missing_complete = self.product.json(
            "POST",
            "/api/live-sessions/999/complete",
        )
        missing_audio = self.product.request(
            "GET",
            "/api/audio/live-observations/999",
        )

        self.assertEqual(404, missing_get["status"], missing_get["body"])
        self.assertEqual(404, missing_post["status"], missing_post["body"])
        self.assertEqual(404, missing_complete["status"], missing_complete["body"])
        self.assertEqual(404, missing_audio["status"], missing_audio["body"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
