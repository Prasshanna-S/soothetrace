import http.client
import json
import plistlib
import math
import ssl
import struct
import tempfile
import threading
import unittest
import uuid
import wave
from pathlib import Path

from spikes.mobile_capture.server import SpikeStore, build_http_server, decode_upload
from spikes.mobile_capture.bootstrap import (
    CERTIFICATE_PATH,
    build_bootstrap_server,
    build_mobileconfig,
    certificate_der_from_pem,
)


class SpikeStoreTests(unittest.TestCase):
    """Break caught: browser-controlled identifiers escaping the spike data root."""

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.root = Path(self.tempdir.name)
        self.store = SpikeStore(self.root)

    def test_create_session_uses_server_generated_uuid_directory(self):
        session_id = self.store.create_session()

        self.assertEqual(str(uuid.UUID(session_id)), session_id)
        self.assertEqual(
            (self.root / "sessions" / session_id).resolve(),
            self.store.session_dir(session_id),
        )
        self.assertTrue(self.store.session_dir(session_id).is_dir())

    def test_session_dir_rejects_browser_controlled_path(self):
        with self.assertRaises(ValueError):
            self.store.session_dir("../../outside")

    def test_upload_path_rejects_invalid_sequence_before_forming_path(self):
        session_id = self.store.create_session()

        with self.assertRaises(ValueError):
            self.store.upload_path(session_id, "../1", "audio/mp4")

    def test_event_round_trip_preserves_order(self):
        session_id = self.store.create_session()

        self.store.append_event(session_id, {"kind": "recording.start", "client_ms": 1})
        self.store.append_event(session_id, {"kind": "track.mute", "client_ms": 2})

        self.assertEqual(
            [
                {"kind": "recording.start", "client_ms": 1},
                {"kind": "track.mute", "client_ms": 2},
            ],
            self.store.read_events(session_id),
        )

    def test_save_upload_rejects_empty_payload(self):
        session_id = self.store.create_session()

        with self.assertRaises(ValueError):
            self.store.save_upload(session_id, 0, "audio/mp4", b"")

    def test_save_upload_uses_safe_server_path_and_exact_bytes(self):
        session_id = self.store.create_session()

        saved = self.store.save_upload(session_id, 7, "audio/mp4", b"phone-audio")

        self.assertEqual("capture-0007.m4a", saved.name)
        self.assertEqual(b"phone-audio", saved.read_bytes())
        self.assertEqual(self.store.session_dir(session_id), saved.parent)

    def test_upload_path_normalizes_safari_mime_spacing(self):
        session_id = self.store.create_session()

        path = self.store.upload_path(
            session_id,
            0,
            "audio/mp4; codecs=mp4a.40.2",
        )

        self.assertEqual("capture-0000.m4a", path.name)


class DecodeUploadTests(unittest.TestCase):
    """Break caught: accepting a browser blob that ffmpeg cannot turn into canonical WAV."""

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.root = Path(self.tempdir.name)

    def write_tone(self, path: Path, seconds: float = 1.0):
        sample_rate = 8000
        frames = bytearray()
        for index in range(int(sample_rate * seconds)):
            value = int(12000 * math.sin(2 * math.pi * 440 * index / sample_rate))
            frames.extend(struct.pack("<h", value))
        with wave.open(str(path), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(sample_rate)
            handle.writeframes(bytes(frames))

    def test_decode_upload_creates_measured_16khz_mono_wav(self):
        source = self.root / "browser-input.wav"
        decoded = self.root / "decoded.wav"
        self.write_tone(source)

        result = decode_upload(source, decoded)

        self.assertTrue(result["ok"], result)
        self.assertTrue(decoded.is_file())
        self.assertEqual(16000, result["sample_rate"])
        self.assertEqual(1, result["channels"])
        self.assertAlmostEqual(1.0, result["duration_s"], places=2)
        self.assertEqual(64, len(result["sha256"]))
        self.assertGreater(result["peak_db"], -20.0)

    def test_decode_upload_rejects_corrupt_browser_blob(self):
        source = self.root / "corrupt.bin"
        decoded = self.root / "decoded.wav"
        source.write_bytes(b"not an audio container")

        result = decode_upload(source, decoded)

        self.assertFalse(result["ok"])
        self.assertFalse(decoded.exists())
        self.assertIn("ffmpeg", result["error"].lower())


class CertificateBootstrapTests(unittest.TestCase):
    """Break caught: iOS receiving a plain file instead of an installable profile."""

    def test_portable_generator_creates_a_valid_ca_and_lan_server_certificate(self):
        from cryptography import x509
        from cryptography.x509.oid import ExtendedKeyUsageOID
        from spikes.mobile_capture.certificates import generate_certificates

        with tempfile.TemporaryDirectory() as tempdir:
            paths = generate_certificates("192.168.50.23", Path(tempdir))
            root = x509.load_pem_x509_certificate(paths.root_certificate.read_bytes())
            server = x509.load_pem_x509_certificate(paths.server_certificate.read_bytes())

            self.assertTrue(paths.root_private_key.is_file())
            self.assertTrue(paths.server_private_key.is_file())
            self.assertEqual(root.subject, root.issuer)
            self.assertTrue(
                root.extensions.get_extension_for_class(
                    x509.BasicConstraints
                ).value.ca
            )
            self.assertEqual(root.subject, server.issuer)
            self.assertFalse(
                server.extensions.get_extension_for_class(
                    x509.BasicConstraints
                ).value.ca
            )
            usages = server.extensions.get_extension_for_class(
                x509.ExtendedKeyUsage
            ).value
            self.assertIn(ExtendedKeyUsageOID.SERVER_AUTH, usages)
            san = server.extensions.get_extension_for_class(
                x509.SubjectAlternativeName
            ).value
            self.assertEqual(
                {"192.168.50.23", "127.0.0.1"},
                {str(value) for value in san.get_values_for_type(x509.IPAddress)},
            )
            self.assertEqual(
                ["localhost"],
                san.get_values_for_type(x509.DNSName),
            )

    def test_portable_generator_rejects_a_non_ip_address(self):
        from spikes.mobile_capture.certificates import generate_certificates

        with tempfile.TemporaryDirectory() as tempdir:
            with self.assertRaises(ValueError):
                generate_certificates("not-a-lan-ip", Path(tempdir))

    def test_existing_server_certificate_must_match_the_current_lan_ip(self):
        from spikes.mobile_capture.certificates import (
            generate_certificates,
            server_certificate_matches_ip,
        )

        with tempfile.TemporaryDirectory() as tempdir:
            paths = generate_certificates("192.168.50.23", Path(tempdir))

            self.assertTrue(
                server_certificate_matches_ip(
                    paths.server_certificate,
                    "192.168.50.23",
                )
            )
            self.assertFalse(
                server_certificate_matches_ip(
                    paths.server_certificate,
                    "192.168.50.24",
                )
            )

    def test_mobileconfig_embeds_root_certificate_payload(self):
        certificate_der = b"\x30\x03\x02\x01\x00"

        payload = plistlib.loads(build_mobileconfig(certificate_der))

        self.assertEqual("Configuration", payload["PayloadType"])
        self.assertEqual("Interaction Memory Local Spike CA", payload["PayloadDisplayName"])
        self.assertEqual(1, len(payload["PayloadContent"]))
        certificate = payload["PayloadContent"][0]
        self.assertEqual("com.apple.security.root", certificate["PayloadType"])
        self.assertEqual(certificate_der, certificate["PayloadContent"])

    def test_pem_conversion_returns_exact_der_bytes_once(self):
        certificate_der = b"\x30\x03\x02\x01\x00"
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "root.pem"
            path.write_text(ssl.DER_cert_to_PEM_cert(certificate_der), encoding="ascii")

            converted = certificate_der_from_pem(path)

        self.assertEqual(certificate_der, converted)

    def test_bootstrap_serves_der_certificate_as_recognized_cer_file(self):
        certificate_der = b"\x30\x03\x02\x01\x00"
        profile = build_mobileconfig(certificate_der)
        server = build_bootstrap_server(("127.0.0.1", 0), certificate_der, profile)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        connection = http.client.HTTPConnection(
            "127.0.0.1", server.server_address[1], timeout=3
        )
        self.addCleanup(connection.close)

        connection.request("GET", CERTIFICATE_PATH)
        response = connection.getresponse()

        self.assertEqual(200, response.status)
        self.assertEqual("application/pkix-cert", response.getheader("Content-Type"))
        self.assertIn(".cer", response.getheader("Content-Disposition"))
        self.assertEqual(certificate_der, response.read())


class SpikeHTTPTests(unittest.TestCase):
    """Break caught: the real HTTP boundary failing to issue a usable server session."""

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        root = Path(self.tempdir.name)
        self.index = root / "index.html"
        self.index.write_text("<!doctype html><title>spike</title>", encoding="utf-8")
        (root / "app.js").write_text("console.log('spike')", encoding="utf-8")
        (root / "app.css").write_text("body { color: black; }", encoding="utf-8")
        self.store = SpikeStore(root / "data")
        self.server = build_http_server(("127.0.0.1", 0), self.store, self.index)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection(
            "127.0.0.1", self.server.server_address[1], timeout=3
        )
        self.addCleanup(connection.close)
        connection.request(method, path, body=body, headers=headers or {})
        return connection.getresponse()

    def test_post_session_returns_canonical_server_uuid(self):
        response = self.request("POST", "/api/session", body=b"")

        self.assertEqual(201, response.status)
        payload = json.loads(response.read())
        self.assertEqual(str(uuid.UUID(payload["session_id"])), payload["session_id"])
        self.assertEqual("no-store", response.getheader("Cache-Control"))

    def test_serves_external_assets_under_restrictive_csp(self):
        response = self.request("GET", "/app.css")

        self.assertEqual(200, response.status)
        self.assertEqual("text/css; charset=utf-8", response.getheader("Content-Type"))
        self.assertNotIn("unsafe-inline", response.getheader("Content-Security-Policy"))
        self.assertEqual(b"body { color: black; }", response.read())

    def test_post_event_then_report_returns_event(self):
        session_id = self.store.create_session()
        event = json.dumps({"kind": "visibility.hidden", "client_ms": 31000}).encode()

        response = self.request(
            "POST",
            "/api/events",
            body=event,
            headers={
                "Content-Type": "application/json",
                "Content-Length": str(len(event)),
                "X-Spike-Session": session_id,
            },
        )
        self.assertEqual(201, response.status)
        response.read()

        report = self.request("GET", f"/api/report?session={session_id}")
        self.assertEqual(200, report.status)
        payload = json.loads(report.read())
        self.assertEqual([{"kind": "visibility.hidden", "client_ms": 31000}], payload["events"])
