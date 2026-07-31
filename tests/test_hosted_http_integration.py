"""HTTP integration checks for anonymous hosted visitor isolation."""

from __future__ import annotations

import http.client
import io
import json
import threading
import unittest
import wave
from http.cookies import SimpleCookie
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import numpy as np

from src import encoders, http_api, identity, store, visitor_sessions


def _wav_bytes(frequency: float = 440.0) -> bytes:
    sample_rate = 16_000
    times = np.arange(sample_rate, dtype=np.float64) / sample_rate
    samples = 0.04 * np.sin(2.0 * np.pi * frequency * times)
    output = io.BytesIO()
    with wave.open(output, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(np.round(samples * 32767.0).astype("<i2").tobytes())
    return output.getvalue()


class _Client:
    def __init__(self, server):
        self.server = server
        self.cookie = ""

    def request(self, method: str, path: str, body: bytes = b"", headers=None):
        request_headers = dict(headers or {})
        request_headers.setdefault("Content-Length", str(len(body)))
        if self.cookie:
            request_headers["Cookie"] = self.cookie
        connection = http.client.HTTPConnection(
            "127.0.0.1",
            self.server.server_address[1],
            timeout=10,
        )
        connection.request(method, path, body=body, headers=request_headers)
        response = connection.getresponse()
        payload = response.read()
        response_headers = {
            key.casefold(): value for key, value in response.getheaders()
        }
        set_cookie = response_headers.get("set-cookie")
        if set_cookie:
            parsed = SimpleCookie()
            parsed.load(set_cookie)
            morsel = parsed.get("soothetrace_session")
            self.cookie = (
                f"soothetrace_session={morsel.value}"
                if morsel is not None and morsel.value
                else ""
            )
        connection.close()
        result = {
            "status": response.status,
            "headers": response_headers,
            "body": payload,
        }
        if response_headers.get("content-type", "").startswith("application/json"):
            result["json"] = json.loads(payload.decode("utf-8"))
        return result

    def json(self, method: str, path: str, payload=None):
        body = json.dumps(payload or {}).encode("utf-8")
        return self.request(
            method,
            path,
            body,
            {"Content-Type": "application/json"},
        )


class HostedHttpIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.template_db = root / "template.db"
        self.registry_db = root / "registry.db"
        self.visitor_root = root / "visitors"
        self.audio_root = root / "audio"
        self.static_root = root / "web"
        self.static_root.mkdir()
        (self.static_root / "index.html").write_text(
            "<!doctype html><title>SootheTrace</title>",
            encoding="utf-8",
        )
        store.init_db(str(self.template_db))
        identity.create_profile(
            "Demo Baby",
            identity.KIND_INFANT,
            str(self.template_db),
        )
        self.manager = visitor_sessions.VisitorSessionManager(
            template_db=self.template_db,
            registry_db=self.registry_db,
            visitor_root=self.visitor_root,
            audio_root=self.audio_root,
        )
        self.server = http_api.build_http_server(
            ("127.0.0.1", 0),
            self.audio_root,
            self.static_root,
            db_path=str(self.template_db),
            encoder_status={
                identity.encoder_for(identity.KIND_INFANT): True,
                identity.encoder_for(identity.KIND_IMITATION): True,
            },
            cry_detector_status=True,
            hosted_mode=True,
            visitor_manager=self.manager,
        )
        self.thread = threading.Thread(
            target=self.server.serve_forever,
            daemon=True,
        )
        self.thread.start()
        self.addCleanup(self._close_server)

    def _close_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def test_consent_cookie_and_profile_mutations_are_visitor_isolated(self):
        first = _Client(self.server)
        second = _Client(self.server)

        visitor = first.request("GET", "/api/visitor-session")
        blocked = first.json(
            "POST",
            "/api/profiles",
            {"display_name": "Private Baby", "kind": identity.KIND_INFANT},
        )
        consented = first.json(
            "POST",
            "/api/visitor-session/consent",
            {},
        )
        created = first.json(
            "POST",
            "/api/profiles",
            {"display_name": "Private Baby", "kind": identity.KIND_INFANT},
        )
        first_profiles = first.request("GET", "/api/profiles")
        second_profiles = second.request("GET", "/api/profiles")

        self.assertEqual(200, visitor["status"], visitor["body"])
        self.assertFalse(visitor["json"]["visitor_session"]["consented"])
        self.assertIn("HttpOnly", visitor["headers"]["set-cookie"])
        self.assertIn("SameSite=Lax", visitor["headers"]["set-cookie"])
        self.assertEqual(403, blocked["status"], blocked["body"])
        self.assertTrue(consented["json"]["visitor_session"]["consented"])
        self.assertEqual(201, created["status"], created["body"])
        self.assertEqual(
            ["Demo Baby", "Private Baby"],
            [item["display_name"] for item in first_profiles["json"]["profiles"]],
        )
        self.assertEqual(
            ["Demo Baby"],
            [item["display_name"] for item in second_profiles["json"]["profiles"]],
        )

    def test_live_upload_and_playback_remain_inside_the_visitor(self):
        first = _Client(self.server)
        second = _Client(self.server)
        first.json("POST", "/api/visitor-session/consent", {})
        second.json("POST", "/api/visitor-session/consent", {})
        created = first.json(
            "POST",
            "/api/live-sessions",
            {"kind": "human_baby"},
        )
        session_id = created["json"]["session"]["id"]
        audio = _wav_bytes()

        def encode(encoder_name, _audio_path):
            dimensions = encoders.dim(encoder_name)
            return [1.0] + [0.0] * (dimensions - 1)

        with patch.object(http_api.encoders, "encode", side_effect=encode):
            observed = first.request(
                "POST",
                f"/api/live-sessions/{session_id}/observations",
                audio,
                {
                    "Content-Type": "audio/wav",
                    "X-Capture-Source": "microphone",
                },
            )

        playback_url = observed["json"]["observation"]["playback_url"]
        own_playback = first.request("GET", playback_url)
        other_playback = second.request("GET", playback_url)

        self.assertEqual(201, observed["status"], observed["body"])
        self.assertEqual(200, own_playback["status"], own_playback["body"])
        self.assertEqual("audio/wav", own_playback["headers"]["content-type"])
        self.assertEqual(404, other_playback["status"], other_playback["body"])

    def test_delete_removes_visitor_storage_and_expires_cookie(self):
        client = _Client(self.server)
        client.request("GET", "/api/visitor-session")
        token = client.cookie.split("=", 1)[1]
        context = self.manager.resolve(token)
        self.assertTrue(context.database_path.is_file())
        self.assertTrue(context.audio_root.is_dir())

        deleted = client.request("DELETE", "/api/visitor-session")

        self.assertEqual(200, deleted["status"], deleted["body"])
        self.assertEqual("", client.cookie)
        self.assertFalse(context.database_path.exists())
        self.assertFalse(context.audio_root.exists())
        self.assertIn("Max-Age=0", deleted["headers"]["set-cookie"])

    def test_readiness_does_not_replace_an_explicit_failed_warm_result(self):
        unavailable_server = http_api.build_http_server(
            ("127.0.0.1", 0),
            self.audio_root,
            self.static_root,
            db_path=str(self.template_db),
            encoder_status={},
            cry_detector_status=True,
            hosted_mode=True,
            visitor_manager=self.manager,
        )
        thread = threading.Thread(
            target=unavailable_server.serve_forever,
            daemon=True,
        )
        thread.start()
        def close_unavailable_server():
            unavailable_server.shutdown()
            unavailable_server.server_close()
            thread.join(timeout=5)

        self.addCleanup(close_unavailable_server)
        client = _Client(unavailable_server)

        with (
            patch.object(
                http_api.encoders,
                "available",
                return_value=[
                    identity.encoder_for(identity.KIND_INFANT),
                    identity.encoder_for(identity.KIND_IMITATION),
                ],
            ),
            patch.object(
                http_api.encoders,
                "needs_baseline",
                return_value=False,
            ),
            patch.object(http_api.shutil, "which", return_value="/usr/bin/ffmpeg"),
        ):
            readiness = client.request("GET", "/readyz")

        self.assertEqual(503, readiness["status"], readiness["body"])
        self.assertEqual("not_ready", readiness["json"]["status"])


if __name__ == "__main__":
    unittest.main()
