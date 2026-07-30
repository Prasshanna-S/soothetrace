"""Focused real-backend smoke test for the Windows GitHub Actions lane."""

from __future__ import annotations

import http.client
import json
import math
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUN_WINDOWS_SMOKE = os.environ.get("CRY_MEMORY_WINDOWS_SMOKE") == "1"


def _request(port, method, path, body=None, headers=None):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
    try:
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        payload = response.read()
        return response.status, response.getheaders(), payload
    finally:
        connection.close()


def _available_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


@unittest.skipUnless(
    RUN_WINDOWS_SMOKE,
    "set CRY_MEMORY_WINDOWS_SMOKE=1 in the dedicated Windows CI lane",
)
class WindowsBackendSmokeTests(unittest.TestCase):
    def test_real_windows_backend_model_and_http_flow(self):
        self.assertEqual("win32", sys.platform)
        self.assertIn(" ", str(ROOT), "CI checkout path must contain a space")
        self.assertIsNotNone(shutil.which("ffmpeg"), "ffmpeg must be on PATH")

        from src import encoders, identity

        fixture = ROOT / "demo_assets" / "human_audio" / "prasshanna-01.wav"
        self.assertTrue(fixture.is_file(), fixture)
        self.assertEqual(
            encoders.ECAPA_CRY,
            identity.ENCODER_FOR_KIND[identity.KIND_IMITATION],
        )

        required_encoders = sorted(set(identity.ENCODER_FOR_KIND.values()))
        warmed = encoders.warm(required_encoders)
        self.assertEqual(
            {name: True for name in required_encoders},
            warmed,
            f"encoder warm failed: {warmed}",
        )

        cry_embedding = encoders.encode(encoders.ECAPA_CRY, str(fixture))
        self.assertIsNotNone(cry_embedding, "cry ECAPA encode returned no vector")
        self.assertEqual(192, len(cry_embedding))
        self.assertTrue(all(math.isfinite(value) for value in cry_embedding))

        with tempfile.TemporaryDirectory(prefix="cry memory windows server ") as directory:
            temp_root = Path(directory)
            data_root = temp_root / "managed audio"
            database = temp_root / "backend state" / "episodes.db"
            log_path = temp_root / "server.log"
            port = _available_port()
            baseline_database = ROOT / "data" / "episodes.db"
            self.assertTrue(
                baseline_database.is_file(),
                "Windows setup must build the population baseline database",
            )
            database.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(baseline_database, database)
            command = [
                sys.executable,
                "-u",
                "-m",
                "src.http_api",
                "--http",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--data-root",
                str(data_root),
                "--static-root",
                str(ROOT / "web"),
                "--db",
                str(database),
            ]
            server_environment = os.environ.copy()
            server_environment["IM_OFFLINE"] = "1"
            server_environment["PYTHONUNBUFFERED"] = "1"
            server_environment.pop("OPENAI_API_KEY", None)

            server_log = log_path.open("w", encoding="utf-8")
            process = subprocess.Popen(
                command,
                cwd=ROOT,
                env=server_environment,
                stdin=subprocess.DEVNULL,
                stdout=server_log,
                stderr=subprocess.STDOUT,
            )
            failure = None
            try:
                deadline = time.monotonic() + 360
                health = None
                last_error = None
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        raise RuntimeError(
                            f"server exited during startup with code {process.returncode}"
                        )
                    try:
                        status, _, payload = _request(port, "GET", "/api/health")
                        if status == 200:
                            health = json.loads(payload.decode("utf-8"))
                            break
                        last_error = RuntimeError(f"health returned HTTP {status}")
                    except (OSError, http.client.HTTPException, json.JSONDecodeError) as exc:
                        last_error = exc
                    time.sleep(2)
                if health is None:
                    raise RuntimeError(f"health endpoint did not become ready: {last_error}")

                self.assertTrue(health["ffmpeg"], health)
                self.assertTrue(health["database"], health)
                self.assertEqual("ready", health["status"], health)
                self.assertTrue(health["population_baseline"], health)
                self.assertTrue(health["encoders"]["infant"], health)
                self.assertTrue(health["encoders"]["human_imitation"], health)

                status, headers, payload = _request(port, "GET", "/")
                self.assertEqual(200, status)
                content_type = dict(headers).get("Content-Type", "")
                self.assertIn("text/html", content_type)
                self.assertIn(b"Cry Memory", payload)

                create_body = json.dumps(
                    {"kind": "human_imitation"}
                ).encode("utf-8")
                status, _, payload = _request(
                    port,
                    "POST",
                    "/api/live-sessions",
                    body=create_body,
                    headers={
                        "Content-Type": "application/json",
                        "Content-Length": str(len(create_body)),
                    },
                )
                self.assertEqual(201, status, payload)
                created = json.loads(payload.decode("utf-8"))
                session = created["session"]
                self.assertEqual("open", session["status"])

                audio = fixture.read_bytes()
                status, _, payload = _request(
                    port,
                    "POST",
                    f"/api/live-sessions/{session['id']}/observations",
                    body=audio,
                    headers={
                        "Content-Type": "audio/wav",
                        "Content-Length": str(len(audio)),
                        "X-Capture-Source": "windows-ci-fixture",
                        "X-Capture-Device": "bundled-consented-audio",
                    },
                )
                self.assertEqual(201, status, payload)
                observed = json.loads(payload.decode("utf-8"))
                self.assertEqual(
                    "provisional_created",
                    observed["classification"]["status"],
                )
                self.assertEqual(
                    "Person A",
                    observed["classification"]["participant"]["display_name"],
                )
            except BaseException as exc:
                failure = exc
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=30)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=30)
                server_log.close()

            if failure is not None:
                output = log_path.read_text(encoding="utf-8", errors="replace")
                self.fail(f"{failure}\n\nServer output:\n{output}")


if __name__ == "__main__":
    unittest.main()
