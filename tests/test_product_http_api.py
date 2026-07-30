import http.client
import io
import json
import os
import subprocess
import sys
import threading
import unittest
import uuid
import wave
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import numpy as np


def _wav_bytes(frequency=440.0, seconds=1.0):
    sample_rate = 16000
    times = np.arange(int(sample_rate * seconds), dtype=np.float64) / sample_rate
    samples = 0.04 * np.sin(2.0 * np.pi * frequency * times)
    pcm = np.round(samples * 32767.0).astype("<i2")
    output = io.BytesIO()
    with wave.open(output, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(pcm.tobytes())
    return output.getvalue()


class ProductServer:
    def __init__(self, encoder_status=None, cry_detector_status=None):
        from src import http_api

        self.temp = TemporaryDirectory()
        root = Path(self.temp.name)
        self.data_root = root / "audio"
        self.static_root = root / "web"
        self.static_root.mkdir()
        (self.static_root / "index.html").write_text(
            "<!doctype html><title>Cry Memory</title>",
            encoding="utf-8",
        )
        (self.static_root / "app.js").write_text('"use strict";', encoding="utf-8")
        (self.static_root / "app.css").write_text("body{}", encoding="utf-8")
        (self.static_root / "manifest.webmanifest").write_text(
            '{"name":"Cry Memory"}',
            encoding="utf-8",
        )
        self.db_path = str(root / "episodes.db")
        self.server = http_api.build_http_server(
            ("127.0.0.1", 0),
            self.data_root,
            self.static_root,
            db_path=self.db_path,
            encoder_status=encoder_status,
            cry_detector_status=cry_detector_status,
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.temp.cleanup()

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection(
            "127.0.0.1",
            self.server.server_address[1],
            timeout=10,
        )
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        payload = response.read()
        response_headers = {
            key.casefold(): value for key, value in response.getheaders()
        }
        result = {
            "status": response.status,
            "headers": response_headers,
            "body": payload,
        }
        if response_headers.get("content-type", "").startswith("application/json"):
            result["json"] = json.loads(payload.decode("utf-8"))
        connection.close()
        return result

    def json(self, method, path, payload=None):
        body = json.dumps(payload or {}).encode("utf-8")
        response = self.request(
            method,
            path,
            body,
            {"Content-Type": "application/json", "Content-Length": str(len(body))},
        )
        return response


class HttpApiTests(unittest.TestCase):
    def setUp(self):
        self.product = ProductServer()
        self.addCleanup(self.product.close)

    def test_health_and_static_responses_have_demo_security_headers(self):
        health = self.product.request("GET", "/api/health")
        page = self.product.request("GET", "/")

        self.assertEqual(200, health["status"])
        payload = json.loads(health["body"].decode("utf-8"))
        self.assertEqual("degraded", payload["status"])
        self.assertIs(payload["population_baseline"], False)
        self.assertIs(payload["capture"]["https_required"], True)
        self.assertEqual(67108864, payload["capture"]["max_upload_bytes"])
        self.assertEqual("no-store", health["headers"]["cache-control"])
        self.assertEqual("nosniff", health["headers"]["x-content-type-options"])
        self.assertNotIn("access-control-allow-origin", health["headers"])
        self.assertEqual(200, page["status"])
        self.assertIn("content-security-policy", page["headers"])

    def test_health_reports_a_model_that_failed_to_warm_as_unavailable(self):
        from src import encoders, http_api

        product = ProductServer(
            encoder_status={
                encoders.MFCC87: True,
                encoders.ECAPA_CRY: False,
            }
        )
        self.addCleanup(product.close)

        with patch.object(http_api.encoders, "needs_baseline", return_value=False):
            health = product.request("GET", "/api/health")["json"]

        self.assertIs(health["encoders"]["infant"], True)
        self.assertIs(health["encoders"]["human_imitation"], False)
        self.assertEqual("degraded", health["status"])

    def test_module_cli_documents_the_https_product_server_arguments(self):
        completed = subprocess.run(
            [sys.executable, "-m", "src.http_api", "--help"],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertIn("--cert", completed.stdout)
        self.assertIn("--key", completed.stdout)
        self.assertIn("--static-root", completed.stdout)
        self.assertIn("--data-root", completed.stdout)

    def test_module_cli_can_serve_plain_http_on_laptop_loopback(self):
        from src import http_api

        class FakeServer:
            def __init__(self):
                self.socket = object()
                self.closed = False

            def serve_forever(self):
                raise KeyboardInterrupt

            def server_close(self):
                self.closed = True

        server = FakeServer()
        with (
            patch.object(
                http_api,
                "build_http_server",
                return_value=server,
            ) as build_server,
            patch.object(http_api.encoders, "warm", return_value={}),
            patch.object(http_api.cry_gate, "warm", return_value=True) as warm_cry,
            redirect_stdout(io.StringIO()),
        ):
            try:
                code = http_api.main(
                    [
                        "--http",
                        "--host",
                        "127.0.0.1",
                        "--port",
                        "8000",
                        "--data-root",
                        "/tmp/interaction-memory-test-audio",
                        "--static-root",
                        "/tmp/interaction-memory-test-web",
                        "--db",
                        "/tmp/interaction-memory-test.db",
                    ]
                )
            except SystemExit as exc:
                code = exc.code

        self.assertEqual(0, code)
        self.assertTrue(server.closed)
        warm_cry.assert_called_once_with()
        self.assertIs(
            True,
            build_server.call_args.kwargs["cry_detector_status"],
        )

    def test_module_cli_rejects_plain_http_on_a_network_interface(self):
        from src import http_api

        with patch.object(
            http_api,
            "build_http_server",
            side_effect=AssertionError("unsafe network server must not start"),
        ), redirect_stderr(io.StringIO()):
            try:
                code = http_api.main(
                    [
                        "--http",
                        "--host",
                        "0.0.0.0",
                    ]
                )
            except SystemExit as exc:
                code = exc.code

        self.assertEqual(2, code)

    def test_profile_creation_validation_and_listing(self):
        malformed = self.product.request(
            "POST",
            "/api/profiles",
            b"{",
            {"Content-Type": "application/json", "Content-Length": "1"},
        )
        invalid = self.product.json(
            "POST",
            "/api/profiles",
            {"display_name": "", "kind": "cat"},
        )
        created = self.product.json(
            "POST",
            "/api/profiles",
            {"display_name": "Baby A", "kind": "infant"},
        )
        listed = self.product.request("GET", "/api/profiles")

        self.assertEqual(400, malformed["status"])
        self.assertEqual(400, invalid["status"])
        self.assertEqual(201, created["status"])
        self.assertEqual("Baby A", created["json"]["profile"]["display_name"])
        profiles = json.loads(listed["body"].decode("utf-8"))["profiles"]
        self.assertEqual(["Baby A"], [profile["display_name"] for profile in profiles])

    def test_profile_delete_supports_a_clean_demo_session(self):
        first = self.product.json(
            "POST",
            "/api/profiles",
            {"display_name": "Participant A", "kind": "human_imitation"},
        )["json"]["profile"]
        self.product.json(
            "POST",
            "/api/profiles",
            {"display_name": "Participant B", "kind": "human_imitation"},
        )

        deleted = self.product.request("DELETE", f"/api/profiles/{first['id']}")
        listed = self.product.request("GET", "/api/profiles")

        self.assertEqual(200, deleted["status"])
        self.assertTrue(json.loads(deleted["body"].decode("utf-8"))["deleted"])
        profiles = json.loads(listed["body"].decode("utf-8"))["profiles"]
        self.assertEqual(["Participant B"], [profile["display_name"] for profile in profiles])

    def test_enrollment_upload_is_decoded_into_server_owned_storage(self):
        from src import identity

        profile = self.product.json(
            "POST",
            "/api/profiles",
            {"display_name": "Baby A", "kind": "infant"},
        )["json"]["profile"]
        audio = _wav_bytes()
        enrolled = self.product.request(
            "POST",
            f"/api/profiles/{profile['id']}/enroll",
            audio,
            {
                "Content-Type": "audio/wav",
                "Content-Length": str(len(audio)),
                "X-Capture-Device": "iPhone Safari",
            },
        )

        self.assertEqual(201, enrolled["status"])
        payload = json.loads(enrolled["body"].decode("utf-8"))
        self.assertEqual("enrolled", payload["status"])
        self.assertEqual(1, identity.get_profile(profile["id"], self.product.db_path)["enrollments"])
        managed = self.product.data_root / "managed"
        self.assertTrue(any(managed.glob("*/source.wav")))
        self.assertTrue(any(managed.glob("*/canonical.wav")))
        self.assertTrue(any(managed.glob("*/identity.wav")))

    def test_attempt_capture_returns_human_state_without_debug_scores(self):
        from src import http_api

        profile = self.product.json(
            "POST",
            "/api/profiles",
            {"display_name": "Baby A", "kind": "infant"},
        )["json"]["profile"]
        attempt = self.product.json(
            "POST",
            "/api/identity/attempts",
            {"kind": "infant"},
        )["json"]["attempt"]
        audio = _wav_bytes()
        internal = {
            "id": attempt["id"],
            "kind": "infant",
            "status": "match",
            "matched_profile_id": profile["id"],
            "retry_allowed": False,
            "resolution_path": "first_capture",
            "resolution_source": "system",
            "capture_status": "match",
            "captures": [
                {
                    "status": "match",
                    "band": "strong",
                    "score": 0.987654,
                    "margin": 0.234567,
                    "candidates": [
                        {"profile_id": profile["id"], "display_name": "Baby A", "score": 0.987654}
                    ],
                    "reasons": ["acoustically_consistent_with_enrolled_profile"],
                }
            ],
        }
        with patch.object(
            http_api.identity,
            "add_identity_capture",
            return_value=internal,
        ):
            response = self.product.request(
                "POST",
                f"/api/identity/attempts/{attempt['id']}/captures",
                audio,
                {"Content-Type": "audio/wav", "Content-Length": str(len(audio))},
            )

        self.assertEqual(200, response["status"])
        payload = json.loads(response["body"].decode("utf-8"))
        self.assertEqual("match", payload["identity"]["status"])
        self.assertEqual("Baby A", payload["identity"]["profile"]["display_name"])
        encoded = json.dumps(payload)
        self.assertNotIn("score", encoded)
        self.assertNotIn("margin", encoded)
        self.assertNotIn("candidates", encoded)
        self.assertNotIn("0.987654", encoded)

    def test_uncertain_result_can_show_a_non_confirmed_direction_without_scores(self):
        from src import http_api

        profile = self.product.json(
            "POST",
            "/api/profiles",
            {"display_name": "Second person", "kind": "human_imitation"},
        )["json"]["profile"]
        attempt = self.product.json(
            "POST",
            "/api/identity/attempts",
            {"kind": "human_imitation"},
        )["json"]["attempt"]
        internal = {
            "id": attempt["id"],
            "kind": "human_imitation",
            "status": "open",
            "nominated_profile_id": profile["id"],
            "retry_allowed": True,
            "capture_status": "uncertain",
            "captures": [
                {
                    "status": "uncertain",
                    "band": "none",
                    "score": 0.514303,
                    "margin": 0.198474,
                    "pool_size": 2,
                    "reasons": ["close_top_profiles"],
                }
            ],
        }
        audio = _wav_bytes()
        with patch.object(
            http_api.identity,
            "add_identity_capture",
            return_value=internal,
        ):
            response = self.product.request(
                "POST",
                f"/api/identity/attempts/{attempt['id']}/captures",
                audio,
                {"Content-Type": "audio/wav", "Content-Length": str(len(audio))},
            )

        self.assertEqual(200, response["status"])
        payload = json.loads(response["body"].decode("utf-8"))["identity"]
        self.assertEqual("uncertain", payload["status"])
        self.assertEqual("Second person", payload["leaning_profile"]["display_name"])
        self.assertEqual("close_call_not_confirmed", payload["direction"])
        self.assertNotIn("novelty", payload)
        encoded = json.dumps(payload)
        self.assertNotIn("score", encoded)
        self.assertNotIn("margin", encoded)
        self.assertNotIn("0.514303", encoded)

    def test_below_every_profile_can_expose_a_new_person_candidate_without_scores(self):
        from src import http_api

        profile = self.product.json(
            "POST",
            "/api/profiles",
            {"display_name": "Person A", "kind": "human_imitation"},
        )["json"]["profile"]
        attempt = self.product.json(
            "POST",
            "/api/identity/attempts",
            {"kind": "human_imitation"},
        )["json"]["attempt"]
        internal = {
            "id": attempt["id"],
            "kind": "human_imitation",
            "status": "open",
            "nominated_profile_id": profile["id"],
            "retry_allowed": True,
            "capture_status": "uncertain",
            "captures": [
                {
                    "status": "uncertain",
                    "band": "none",
                    "score": 0.2,
                    "margin": 0.1,
                    "pool_size": 3,
                    "reasons": [
                        "below_accept_threshold",
                        "new_or_unenrolled_source",
                    ],
                }
            ],
        }
        audio = _wav_bytes()
        with patch.object(
            http_api.identity,
            "add_identity_capture",
            return_value=internal,
        ):
            response = self.product.request(
                "POST",
                f"/api/identity/attempts/{attempt['id']}/captures",
                audio,
                {"Content-Type": "audio/wav", "Content-Length": str(len(audio))},
            )

        self.assertEqual(200, response["status"])
        payload = json.loads(response["body"].decode("utf-8"))["identity"]
        self.assertEqual("uncertain", payload["status"])
        self.assertEqual("candidate_new_profile", payload["novelty"])
        self.assertEqual("Person A", payload["closest_profile"]["display_name"])
        self.assertEqual("outside_profiles_not_confirmed", payload["direction"])
        encoded = json.dumps(payload)
        self.assertNotIn("score", encoded)
        self.assertNotIn("margin", encoded)
        self.assertNotIn("0.2", encoded)

    def test_consistent_novelty_retry_exposes_confirmed_new_profile_without_scores(self):
        from src import http_api

        profile = self.product.json(
            "POST",
            "/api/profiles",
            {"display_name": "Person A", "kind": "human_imitation"},
        )["json"]["profile"]
        attempt = self.product.json(
            "POST",
            "/api/identity/attempts",
            {"kind": "human_imitation"},
        )["json"]["attempt"]
        internal = {
            "id": attempt["id"],
            "kind": "human_imitation",
            "status": "unresolved",
            "nominated_profile_id": profile["id"],
            "retry_allowed": True,
            "capture_status": "uncertain",
            "reasons": [
                "below_accept_threshold",
                "new_or_unenrolled_source",
                "novelty_pair_consistent",
                "new_profile_candidate_confirmed",
            ],
            "captures": [
                {
                    "status": "uncertain",
                    "band": "none",
                    "score": 0.2,
                    "margin": 0.1,
                    "pool_size": 1,
                    "top_profile_id": profile["id"],
                    "reasons": [
                        "below_accept_threshold",
                        "new_or_unenrolled_source",
                    ],
                }
            ],
        }
        audio = _wav_bytes()
        with patch.object(
            http_api.identity,
            "retry_identity_attempt",
            return_value=internal,
        ):
            response = self.product.request(
                "POST",
                f"/api/identity/attempts/{attempt['id']}/retry",
                audio,
                {"Content-Type": "audio/wav", "Content-Length": str(len(audio))},
            )

        self.assertEqual(200, response["status"])
        payload = json.loads(response["body"].decode("utf-8"))["identity"]
        self.assertEqual("unresolved", payload["status"])
        self.assertEqual("confirmed_new_profile", payload["novelty"])
        self.assertEqual("Person A", payload["closest_profile"]["display_name"])
        encoded = json.dumps(payload)
        self.assertNotIn("score", encoded)
        self.assertNotIn("margin", encoded)

    def test_incident_completion_is_blocked_until_identity_matches(self):
        attempt = self.product.json(
            "POST",
            "/api/identity/attempts",
            {"kind": "infant"},
        )["json"]["attempt"]

        response = self.product.json(
            "POST",
            f"/api/incidents/{attempt['id']}/complete",
            {"caregiver_answer": "Rocking worked.", "tags": ["overtired"]},
        )

        self.assertEqual(409, response["status"])
        self.assertEqual("identity_not_matched", response["json"]["reason"])

    def test_repeated_incident_completion_returns_conflict(self):
        from src import http_api

        with patch.object(
            http_api.careflow,
            "complete_incident",
            return_value={
                "status": "conflict",
                "reason": "incident_already_completed",
            },
        ):
            response = self.product.json(
                "POST",
                "/api/incidents/39/complete",
                {"caregiver_answer": "Rocking worked."},
            )

        self.assertEqual(409, response["status"])
        self.assertEqual("incident_already_completed", response["json"]["reason"])

    def test_incident_preview_returns_history_without_a_new_episode(self):
        from src import http_api

        preview_result = {
            "status": "preview",
            "identity": {
                "profile_id": 7,
                "display_name": "Baby A",
                "kind": "infant",
            },
            "scenarios": [
                {
                    "episode_id": 12,
                    "band": "weak",
                    "started_at": "2026-07-20T03:00:00-04:00",
                    "interventions": [],
                    "outcome": "The baby settled.",
                    "outcome_src": "caregiver",
                    "worked": True,
                    "contributions": {},
                }
            ],
            "guidance": {
                "status": "grounded",
                "recommendation": "What helped before: walked.",
            },
        }
        with patch.object(
            http_api.careflow,
            "preview_incident",
            return_value=preview_result,
            create=True,
        ) as preview:
            response = self.product.json(
                "POST",
                "/api/incidents/42/preview",
                {"tags": ["evening"]},
            )

        self.assertEqual(200, response["status"])
        self.assertEqual("preview", response["json"]["status"])
        self.assertNotIn("episode", response["json"])
        self.assertEqual(
            "/api/audio/episodes/12",
            response["json"]["scenarios"][0]["audio_url"],
        )
        preview.assert_called_once_with(
            42,
            explicit_tags=["evening"],
            db_path=self.product.db_path,
        )

    def test_audio_playback_allows_only_database_owned_managed_paths(self):
        from src import store

        managed = self.product.data_root / "managed" / "known"
        managed.mkdir(parents=True)
        safe_audio = managed / "canonical.wav"
        safe_audio.write_bytes(_wav_bytes())
        safe_id = store.save_episode(
            {
                "subject_id": "profile-1",
                "audio_path": str(safe_audio),
                "fingerprint": [0.0] * 87,
            },
            self.product.db_path,
        )
        outside = Path(self.product.temp.name) / "outside.wav"
        outside.write_bytes(_wav_bytes())
        outside_id = store.save_episode(
            {
                "subject_id": "profile-1",
                "audio_path": str(outside),
                "fingerprint": [0.0] * 87,
            },
            self.product.db_path,
        )

        allowed = self.product.request("GET", f"/api/audio/episodes/{safe_id}")
        denied = self.product.request("GET", f"/api/audio/episodes/{outside_id}")
        traversal = self.product.request("GET", "/api/audio/episodes/../../etc/passwd")

        self.assertEqual(200, allowed["status"])
        self.assertEqual("audio/wav", allowed["headers"]["content-type"])
        self.assertEqual(safe_audio.read_bytes(), allowed["body"])
        self.assertEqual(404, denied["status"])
        self.assertEqual(404, traversal["status"])


class CareSessionHttpApiTests(unittest.TestCase):
    def setUp(self):
        self.product = ProductServer(cry_detector_status=True)
        self.addCleanup(self.product.close)

    def _profile(self, name="Baby A", kind="infant"):
        return self.product.json(
            "POST",
            "/api/profiles",
            {"display_name": name, "kind": kind},
        )["json"]["profile"]

    def _care_session(self, profile_id=None, tags=None):
        profile_id = profile_id or self._profile()["id"]
        response = self.product.json(
            "POST",
            "/api/care-sessions",
            {"profile_id": profile_id, "tags": tags or []},
        )
        self.assertEqual(201, response["status"], response)
        return response["json"]["session"]

    def _ingest_result(self, payload, status="ready", reason=None):
        capture = self.product.data_root / "managed" / str(uuid.uuid4())
        capture.mkdir(parents=True)
        source = capture / "source.m4a"
        source.write_bytes(payload)
        result = {
            "status": status,
            "source_path": str(source),
            "capture": {},
        }
        if status == "ready":
            canonical = capture / "canonical.wav"
            identity_path = capture / "identity.wav"
            canonical.write_bytes(_wav_bytes())
            identity_path.write_bytes(_wav_bytes())
            result.update(
                {
                    "canonical_path": str(canonical),
                    "identity_path": str(identity_path),
                    "quality": {"duration_s": 1.0},
                }
            )
        else:
            result["reason"] = reason or "decode_failed"
        return result

    def test_health_uses_prewarmed_cry_status_without_warming_on_request(self):
        from src import config, cry_gate, encoders, http_api, store

        store.save_baseline(
            config.POPULATION_KEY,
            np.zeros(87),
            np.ones(87),
            421,
            self.product.db_path,
        )
        with (
            patch.object(http_api.encoders, "needs_baseline", return_value=True),
            patch.object(
                http_api.shutil,
                "which",
                side_effect=lambda name: "/usr/bin/ffmpeg" if name == "ffmpeg" else None,
            ),
            patch.object(cry_gate, "warm") as warm,
        ):
            ready_product = ProductServer(
                encoder_status={
                    encoders.MFCC87: True,
                    encoders.ECAPA_CRY: True,
                },
                cry_detector_status=True,
            )
            self.addCleanup(ready_product.close)
            store.save_baseline(
                config.POPULATION_KEY,
                np.zeros(87),
                np.ones(87),
                421,
                ready_product.db_path,
            )
            ready = ready_product.request("GET", "/api/health")["json"]
            unavailable_product = ProductServer(
                encoder_status={
                    encoders.MFCC87: True,
                    encoders.ECAPA_CRY: True,
                },
                cry_detector_status=False,
            )
            self.addCleanup(unavailable_product.close)
            store.save_baseline(
                config.POPULATION_KEY,
                np.zeros(87),
                np.ones(87),
                421,
                unavailable_product.db_path,
            )
            unavailable = unavailable_product.request("GET", "/api/health")["json"]

        self.assertIs(ready["care"]["ready"], True)
        self.assertEqual(
            {
                "ready": True,
                "model_version": config.CRY_GATE_MODEL_VERSION,
            },
            ready["care"]["cry_detector"],
        )
        self.assertIs(ready["whisper"], False)
        self.assertIs(unavailable["care"]["ready"], False)
        self.assertEqual(
            {key: ready[key] for key in ready if key != "care"},
            {key: unavailable[key] for key in unavailable if key != "care"},
        )
        warm.assert_not_called()

    def test_care_readiness_requires_each_non_whisper_dependency(self):
        from src import config, encoders, http_api, store

        cases = (
            ("ffmpeg", False, True, True, True, False),
            ("database", True, False, True, True, False),
            ("infant_encoder", True, True, False, True, False),
            ("population_baseline", True, True, True, False, False),
        )
        for _, ffmpeg, database, infant, baseline, expected in cases:
            with self.subTest(_):
                product = ProductServer(
                    encoder_status={
                        encoders.MFCC87: infant,
                        encoders.ECAPA_CRY: True,
                    },
                    cry_detector_status=True,
                )
                self.addCleanup(product.close)
                if baseline:
                    store.save_baseline(
                        config.POPULATION_KEY,
                        np.zeros(87),
                        np.ones(87),
                        421,
                        product.db_path,
                    )
                if not database:
                    Path(product.db_path).unlink()
                with (
                    patch.object(
                        http_api.shutil,
                        "which",
                        side_effect=lambda name: (
                            "/usr/bin/ffmpeg" if name == "ffmpeg" and ffmpeg else None
                        ),
                    ),
                    patch.object(http_api.encoders, "needs_baseline", return_value=True),
                    patch.object(http_api.store, "init_db") if not database else patch.object(
                        http_api.store,
                        "init_db",
                        wraps=http_api.store.init_db,
                    ),
                ):
                    payload = product.request("GET", "/api/health")["json"]
                self.assertIs(payload["care"]["ready"], expected)

    def test_create_read_and_transitions_are_profile_scoped_and_allowlisted(self):
        from src import care_sessions, http_api

        profile = self._profile()
        imitation = self._profile("Adult", "human_imitation")
        unavailable = ProductServer(cry_detector_status=False)
        self.addCleanup(unavailable.close)
        unavailable_profile = unavailable.json(
            "POST",
            "/api/profiles",
            {"display_name": "Baby B", "kind": "infant"},
        )["json"]["profile"]

        blocked = unavailable.json(
            "POST",
            "/api/care-sessions",
            {"profile_id": unavailable_profile["id"]},
        )
        wrong_kind = self.product.json(
            "POST",
            "/api/care-sessions",
            {"profile_id": imitation["id"]},
        )
        malformed = self.product.request(
            "POST",
            "/api/care-sessions",
            b"{",
            {"Content-Type": "application/json", "Content-Length": "1"},
        )
        created = self.product.json(
            "POST",
            "/api/care-sessions",
            {"profile_id": profile["id"], "tags": [" Evening ", "evening"]},
        )

        self.assertEqual(503, blocked["status"])
        self.assertEqual("cry_detector_unavailable", blocked["json"]["reason"])
        self.assertEqual(400, wrong_kind["status"])
        self.assertEqual("invalid_care_session_profile", wrong_kind["json"]["reason"])
        self.assertEqual(400, malformed["status"])
        self.assertEqual(201, created["status"])
        session = created["json"]["session"]
        self.assertEqual(
            {
                "id",
                "status",
                "profile",
                "started_at",
                "paused_at",
                "stopped_at",
                "completed_at",
                "last_sequence",
                "tags",
                "decision",
            },
            set(session),
        )
        self.assertEqual(["evening"], session["tags"])

        read = self.product.request(
            "GET",
            f"/api/care-sessions/{session['id']}",
        )
        paused = self.product.json(
            "POST",
            f"/api/care-sessions/{session['id']}/pause",
        )
        conflict = self.product.json(
            "POST",
            f"/api/care-sessions/{session['id']}/pause",
        )
        resumed = self.product.json(
            "POST",
            f"/api/care-sessions/{session['id']}/resume",
        )
        stopped = self.product.json(
            "POST",
            f"/api/care-sessions/{session['id']}/stop",
        )
        stopped_again = self.product.json(
            "POST",
            f"/api/care-sessions/{session['id']}/stop",
        )

        self.assertEqual(200, read["status"])
        self.assertEqual(200, paused["status"])
        self.assertEqual(409, conflict["status"])
        self.assertEqual("invalid_care_session_transition", conflict["json"]["reason"])
        self.assertEqual(200, resumed["status"])
        self.assertEqual(200, stopped["status"])
        self.assertEqual(stopped["json"], stopped_again["json"])

        internal = dict(care_sessions.get(session["id"], self.product.db_path))
        internal["_score"] = 0.99
        internal["embedding"] = [1.0]
        internal["profile"] = {
            **internal["profile"],
            "source_path": "/secret",
        }
        with patch.object(http_api.care_sessions, "get", return_value=internal):
            safe = self.product.request(
                "GET",
                f"/api/care-sessions/{session['id']}",
            )["json"]
        encoded = json.dumps(safe)
        self.assertNotIn("_score", encoded)
        self.assertNotIn("embedding", encoded)
        self.assertNotIn("source_path", encoded)

    def test_care_session_routes_require_exact_lengths_and_positive_ids(self):
        paths = (
            "/api/care-sessions/not-an-id",
            "/api/care-sessions/0",
            "/api/care-sessions/1/extra",
            "/api/care-sessions/1/pause/extra",
            "/api/profiles/1/incidents/2/audio/extra",
        )
        for path in paths:
            with self.subTest(path=path):
                self.assertEqual(404, self.product.request("GET", path)["status"])

        for path in (
            "/api/care-sessions/0/pause",
            "/api/care-sessions/not-an-id/pause",
            "/api/care-sessions/1/unknown",
        ):
            with self.subTest(path=path):
                self.assertEqual(404, self.product.json("POST", path)["status"])

    def test_chunk_accepts_raw_safari_mp4_and_returns_score_free_result(self):
        from src import care_sessions, http_api

        session = self._care_session()
        raw = b"self-contained-safari-mp4"
        ingested = self._ingest_result(raw)
        with (
            patch.object(
                http_api.audio_ingest,
                "ingest_audio",
                return_value=ingested,
            ) as ingest,
            patch.object(
                care_sessions.cry_gate,
                "classify",
                return_value={
                    "status": "no_cry_detected",
                    "label": None,
                    "reason_codes": ["no_infant_cry_evidence"],
                    "analyzed_duration_s": 1.0,
                    "analysis_view_count": 1,
                    "model_version": "ast-audioset-baby-cry-v1",
                    "_infant_score": 0.01,
                    "_generic_cry_score": 0.02,
                },
            ),
        ):
            response = self.product.request(
                "POST",
                f"/api/care-sessions/{session['id']}/chunks",
                raw,
                {
                    "Content-Type": "audio/mp4; codecs=mp4a.40.2",
                    "Content-Length": str(len(raw)),
                    "X-Capture-Sequence": "1",
                    "X-Capture-Source": "microphone",
                    "X-Capture-Device": "iPhone Safari",
                },
            )

        self.assertEqual(201, response["status"], response)
        result = response["json"]
        self.assertEqual(1, result["session"]["last_sequence"])
        self.assertEqual("no_cry_detected", result["chunk"]["status"])
        encoded = json.dumps(result)
        for forbidden in (
            "score",
            "margin",
            "digest",
            "path",
            "embedding",
            "candidates",
        ):
            self.assertNotIn(forbidden, encoded)
        ingest.assert_called_once_with(
            raw,
            "audio/mp4; codecs=mp4a.40.2",
            capture_metadata={
                "capture_device_name": "iPhone Safari",
                "user_agent": "",
            },
            storage_root=self.product.data_root.resolve(),
        )

    def test_chunk_header_validation_happens_before_ingest(self):
        from src import http_api

        session = self._care_session()
        cases = (None, "0", "-1", "1.5", "word")
        with patch.object(http_api.audio_ingest, "ingest_audio") as ingest:
            for value in cases:
                headers = {
                    "Content-Type": "audio/mp4",
                    "Content-Length": "3",
                }
                if value is not None:
                    headers["X-Capture-Sequence"] = value
                with self.subTest(sequence=value):
                    response = self.product.request(
                        "POST",
                        f"/api/care-sessions/{session['id']}/chunks",
                        b"mp4",
                        headers,
                    )
                    self.assertEqual(400, response["status"])
                    self.assertEqual(
                        "invalid_capture_sequence",
                        response["json"]["reason"],
                    )
        ingest.assert_not_called()

    def test_processed_invalid_chunk_advances_sequence_with_structured_422(self):
        from src import http_api

        session = self._care_session()
        raw = b"undecodable-mp4"
        ingested = self._ingest_result(raw, "invalid", "decode_failed")
        with patch.object(
            http_api.audio_ingest,
            "ingest_audio",
            return_value=ingested,
        ):
            response = self.product.request(
                "POST",
                f"/api/care-sessions/{session['id']}/chunks",
                raw,
                {
                    "Content-Type": "audio/mp4",
                    "Content-Length": str(len(raw)),
                    "X-Capture-Sequence": "1",
                },
            )

        self.assertEqual(422, response["status"], response)
        self.assertEqual(1, response["json"]["session"]["last_sequence"])
        self.assertEqual("invalid", response["json"]["chunk"]["status"])
        self.assertEqual(
            ["decode_failed"],
            response["json"]["chunk"]["reason_codes"],
        )
        self.assertTrue(Path(ingested["source_path"]).is_file())

    def test_duplicate_conflict_and_gap_do_not_orphan_managed_uploads(self):
        from src import care_sessions, http_api

        session = self._care_session()
        accepted = self._ingest_result(b"same")
        duplicate = self._ingest_result(b"same")
        conflict = self._ingest_result(b"different")
        gap = self._ingest_result(b"gap")
        with (
            patch.object(
                http_api.audio_ingest,
                "ingest_audio",
                side_effect=(accepted, duplicate, conflict, gap),
            ),
            patch.object(
                care_sessions.cry_gate,
                "classify",
                return_value={
                    "status": "no_cry_detected",
                    "reason_codes": ["no_infant_cry_evidence"],
                    "model_version": "ast-audioset-baby-cry-v1",
                },
            ),
        ):
            first = self.product.request(
                "POST",
                f"/api/care-sessions/{session['id']}/chunks",
                b"same",
                {
                    "Content-Type": "audio/mp4",
                    "Content-Length": "4",
                    "X-Capture-Sequence": "1",
                },
            )
            replay = self.product.request(
                "POST",
                f"/api/care-sessions/{session['id']}/chunks",
                b"same",
                {
                    "Content-Type": "audio/mp4",
                    "Content-Length": "4",
                    "X-Capture-Sequence": "1",
                },
            )
            conflicting = self.product.request(
                "POST",
                f"/api/care-sessions/{session['id']}/chunks",
                b"different",
                {
                    "Content-Type": "audio/mp4",
                    "Content-Length": "9",
                    "X-Capture-Sequence": "1",
                },
            )
            out_of_order = self.product.request(
                "POST",
                f"/api/care-sessions/{session['id']}/chunks",
                b"gap",
                {
                    "Content-Type": "audio/mp4",
                    "Content-Length": "3",
                    "X-Capture-Sequence": "3",
                },
            )

        self.assertEqual(201, first["status"])
        self.assertEqual(first["json"], replay["json"])
        self.assertEqual(409, conflicting["status"])
        self.assertEqual("sequence_conflict", conflicting["json"]["reason"])
        self.assertEqual(409, out_of_order["status"])
        self.assertEqual("out_of_order_chunk", out_of_order["json"]["reason"])
        self.assertTrue(Path(accepted["source_path"]).parent.is_dir())
        for redundant in (duplicate, conflict, gap):
            self.assertFalse(Path(redundant["source_path"]).parent.exists())

    def test_unexpected_chunk_failure_cleans_only_current_unsaved_ingest(self):
        from src import http_api

        session = self._care_session()
        existing = self.product.data_root / "managed" / "existing"
        existing.mkdir(parents=True)
        existing_file = existing / "canonical.wav"
        existing_file.write_bytes(_wav_bytes())
        current = self._ingest_result(b"current")
        with (
            patch.object(
                http_api.audio_ingest,
                "ingest_audio",
                return_value=current,
            ),
            patch.object(
                http_api.care_sessions,
                "submit_chunk",
                return_value={
                    "status": "error",
                    "reason": "care_session_storage_error",
                },
            ),
        ):
            response = self.product.request(
                "POST",
                f"/api/care-sessions/{session['id']}/chunks",
                b"current",
                {
                    "Content-Type": "audio/mp4",
                    "Content-Length": "7",
                    "X-Capture-Sequence": "1",
                },
            )

        self.assertEqual(500, response["status"])
        self.assertTrue(existing_file.is_file())
        self.assertFalse(Path(current["source_path"]).parent.exists())

    def test_complete_discard_and_profile_scoped_pcm_wav_audio(self):
        from src import care_sessions, http_api, store

        profile = self._profile()
        session = self._care_session(profile["id"])
        no_match = self.product.json(
            "POST",
            f"/api/care-sessions/{session['id']}/stop",
        )
        self.assertEqual(200, no_match["status"])
        invalid = self.product.json(
            "POST",
            f"/api/care-sessions/{session['id']}/complete",
            {"action": "", "settled": "yes"},
        )
        missing_match = self.product.json(
            "POST",
            f"/api/care-sessions/{session['id']}/complete",
            {"action": "Held upright", "settled": True},
        )
        self.assertEqual(400, invalid["status"])
        self.assertEqual("invalid_care_session_completion", invalid["json"]["reason"])
        self.assertEqual(409, missing_match["status"])
        self.assertEqual("no_matched_chunk", missing_match["json"]["reason"])

        completed = {
            "session": {
                **care_sessions.get(session["id"], self.product.db_path),
                "status": "complete",
                "completed_at": "2026-07-30T12:00:00+00:00",
                "_score": 0.9,
            },
            "incident": {
                "id": 71,
                "detail_url": f"/api/profiles/{profile['id']}/incidents/71",
                "audio_path": "/secret",
            },
        }
        with patch.object(
            http_api.care_sessions,
            "complete",
            return_value=completed,
        ):
            saved = self.product.json(
                "POST",
                f"/api/care-sessions/{session['id']}/complete",
                {
                    "action": "Held upright",
                    "settled": True,
                    "notes": "Settled",
                    "tags": ["evening"],
                },
            )
        self.assertEqual(200, saved["status"])
        self.assertEqual(
            {"id", "detail_url"},
            set(saved["json"]["incident"]),
        )
        self.assertNotIn("_score", json.dumps(saved["json"]))
        self.assertNotIn("audio_path", json.dumps(saved["json"]))

        discard_session = self._care_session(profile["id"])
        discarded = self.product.request(
            "DELETE",
            f"/api/care-sessions/{discard_session['id']}",
        )
        discarded_again = self.product.request(
            "DELETE",
            f"/api/care-sessions/{discard_session['id']}",
        )
        self.assertEqual(200, discarded["status"])
        self.assertEqual(discarded["json"], discarded_again["json"])

        managed = self.product.data_root / "managed" / "incident"
        managed.mkdir(parents=True)
        arbitrary_name = managed / "representative-evidence.bin"
        arbitrary_name.write_bytes(_wav_bytes())
        incident_id = store.save_episode(
            {
                "subject_id": f"profile-{profile['id']}",
                "audio_path": str(arbitrary_name),
                "fingerprint": [0.0] * 87,
            },
            self.product.db_path,
        )
        correct = self.product.request(
            "GET",
            f"/api/profiles/{profile['id']}/incidents/{incident_id}/audio",
        )
        wrong_profile = self.product.request(
            "GET",
            f"/api/profiles/{profile['id'] + 1}/incidents/{incident_id}/audio",
        )
        missing = self.product.request(
            "GET",
            f"/api/profiles/{profile['id']}/incidents/{incident_id + 999}/audio",
        )
        self.assertEqual(200, correct["status"])
        self.assertEqual("audio/wav", correct["headers"]["content-type"])
        self.assertEqual(arbitrary_name.read_bytes(), correct["body"])
        self.assertEqual(404, wrong_profile["status"])
        self.assertEqual(wrong_profile["json"], missing["json"])


if __name__ == "__main__":
    unittest.main()
