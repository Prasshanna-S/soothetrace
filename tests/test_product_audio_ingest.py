import math
import os
import unittest
import wave
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import numpy as np

from src import audio_ingest


def _wav_bytes(samples: np.ndarray, sample_rate: int = 16000) -> bytes:
    import io

    buffer = io.BytesIO()
    clipped = np.clip(samples, -1.0, 1.0)
    pcm = np.round(clipped * 32767.0).astype("<i2")
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(pcm.tobytes())
    return buffer.getvalue()


def _read_pcm16(path: str | Path) -> np.ndarray:
    with wave.open(str(path), "rb") as handle:
        if handle.getnchannels() != 1 or handle.getsampwidth() != 2:
            raise AssertionError("fixture output must be mono PCM16")
        frames = handle.readframes(handle.getnframes())
    return np.frombuffer(frames, dtype="<i2").astype(np.float64) / 32768.0


class AudioIngestTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.audio_root = Path(self.temp.name) / "audio"
        self.audio_patch = patch.object(
            audio_ingest.config,
            "AUDIO_DIR",
            str(self.audio_root),
        )
        self.audio_patch.start()
        self.addCleanup(self.audio_patch.stop)

    def test_ingest_normalizes_to_minus_24_db_without_changing_wave_shape(self):
        time = np.arange(16000, dtype=np.float64) / 16000.0
        original = 0.025 * np.sin(2.0 * np.pi * 440.0 * time)

        result = audio_ingest.ingest_audio(_wav_bytes(original), "audio/wav")

        self.assertEqual("ready", result["status"])
        normalized = _read_pcm16(result["identity_path"])
        measured_db = 20.0 * math.log10(
            math.sqrt(float(np.mean(np.square(normalized))))
        )
        self.assertAlmostEqual(-24.0, measured_db, delta=0.03)
        self.assertGreater(float(np.corrcoef(original, normalized)[0, 1]), 0.999)
        self.assertAlmostEqual(
            -24.0,
            result["quality"]["normalized_mean_db"],
            delta=0.03,
        )
        self.assertEqual("rms-24db-v1", result["versions"]["normalization"])

    def test_ingest_rejects_normalization_that_would_clip(self):
        impulsive = np.zeros(16000, dtype=np.float64)
        impulsive[8000] = 0.9

        result = audio_ingest.ingest_audio(_wav_bytes(impulsive), "audio/wav")

        self.assertEqual("invalid", result["status"])
        self.assertEqual("unsafe_normalization_headroom", result["reason"])
        self.assertTrue(Path(result["source_path"]).is_file())
        self.assertTrue(Path(result["canonical_path"]).is_file())
        self.assertFalse((Path(result["canonical_path"]).parent / "identity.wav").exists())

    def test_ingest_rejects_empty_payload_without_creating_a_capture(self):
        result = audio_ingest.ingest_audio(b"", "audio/wav")

        self.assertEqual(
            {"status": "invalid", "reason": "empty_upload"},
            result,
        )
        self.assertFalse(self.audio_root.exists())

    def test_ingest_rejects_payload_over_64_mib(self):
        result = audio_ingest.ingest_audio(
            b"x" * (audio_ingest.MAX_UPLOAD_BYTES + 1),
            "audio/wav",
        )

        self.assertEqual(
            {"status": "invalid", "reason": "upload_too_large"},
            result,
        )
        self.assertFalse(self.audio_root.exists())

    def test_ingest_preserves_source_and_canonical_raw_audio(self):
        time = np.arange(8000, dtype=np.float64) / 16000.0
        payload = _wav_bytes(0.03 * np.sin(2.0 * np.pi * 320.0 * time))

        result = audio_ingest.ingest_audio(
            payload,
            "audio/wav",
            capture_metadata={"device": "iPhone", "mime": "audio/wav"},
        )

        source = Path(result["source_path"])
        canonical = Path(result["canonical_path"])
        identity = Path(result["identity_path"])
        self.assertEqual(payload, source.read_bytes())
        self.assertNotEqual(source, canonical)
        self.assertNotEqual(canonical, identity)
        self.assertTrue(canonical.is_file())
        self.assertEqual(
            {"device": "iPhone", "mime": "audio/wav"},
            result["capture"],
        )
        self.assertEqual(64, len(result["sha256"]))

    def test_ingest_uses_an_explicit_server_storage_root(self):
        time = np.arange(8000, dtype=np.float64) / 16000.0
        payload = _wav_bytes(0.03 * np.sin(2.0 * np.pi * 320.0 * time))
        server_root = Path(self.temp.name) / "server-owned-audio"

        result = audio_ingest.ingest_audio(
            payload,
            "audio/wav",
            storage_root=server_root,
        )

        self.assertEqual("ready", result["status"])
        self.assertEqual(
            (server_root / "managed").resolve(),
            Path(result["source_path"]).resolve().parent.parent,
        )
        self.assertFalse(self.audio_root.exists())

    def test_ingest_ignores_unsafe_upload_identifier(self):
        time = np.arange(4000, dtype=np.float64) / 16000.0
        payload = _wav_bytes(0.04 * np.sin(2.0 * np.pi * 500.0 * time))

        result = audio_ingest.ingest_audio(
            payload,
            "audio/wav",
            upload_id="../../outside",
        )

        capture_dir = Path(result["source_path"]).parent.resolve()
        managed_root = (self.audio_root / "managed").resolve()
        self.assertEqual(managed_root, capture_dir.parent)
        self.assertNotIn("outside", str(capture_dir))
        self.assertFalse((Path(self.temp.name) / "outside").exists())

    def test_ingest_returns_stable_decode_failure_and_preserves_source(self):
        result = audio_ingest.ingest_audio(
            b"not an audio container",
            "audio/mp4; codecs=mp4a.40.2",
        )

        self.assertEqual("invalid", result["status"])
        self.assertEqual("decode_failed", result["reason"])
        self.assertTrue(Path(result["source_path"]).is_file())
        self.assertFalse((Path(result["source_path"]).parent / "canonical.wav").exists())

    def test_ingest_accepts_common_browser_file_picker_audio_types(self):
        time = np.arange(8000, dtype=np.float64) / 16000.0
        payload = _wav_bytes(0.03 * np.sin(2.0 * np.pi * 320.0 * time))

        for mime in ("audio/mpeg", "audio/aac", "audio/x-m4a", "audio/flac"):
            with self.subTest(mime=mime):
                result = audio_ingest.ingest_audio(payload, mime)

                self.assertEqual("ready", result["status"], result)
                self.assertTrue(Path(result["canonical_path"]).is_file())

    def test_ingest_rejects_unsupported_mime_before_writing(self):
        result = audio_ingest.ingest_audio(b"payload", "text/plain")

        self.assertEqual(
            {"status": "invalid", "reason": "unsupported_mime"},
            result,
        )
        self.assertFalse(self.audio_root.exists())


if __name__ == "__main__":
    unittest.main()
