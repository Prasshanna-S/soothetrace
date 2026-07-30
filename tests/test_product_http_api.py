import http.client
import io
import json
import os
import subprocess
import sys
import threading
import unittest
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
    def __init__(self):
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
            patch.object(http_api, "build_http_server", return_value=server),
            patch.object(http_api.encoders, "warm", return_value={}),
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


if __name__ == "__main__":
    unittest.main()
