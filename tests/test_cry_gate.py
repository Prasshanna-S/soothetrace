import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

import numpy as np

from src import cry_gate


def _write_wav(
    path: Path,
    samples: np.ndarray,
    sample_rate: int = 16000,
    channels: int = 1,
) -> None:
    pcm = np.asarray(samples, dtype="<i2")
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(pcm.tobytes())


class CryGateDecisionTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.wav_path = str(Path(self.tempdir.name) / "canonical.wav")
        _write_wav(Path(self.wav_path), np.full(16000, 1000, dtype=np.int16))

    def test_strong_rule_requires_absolute_and_relative_evidence(self):
        with patch.object(cry_gate, "_event_scores", return_value=(0.04, 0.03)):
            result = cry_gate.classify(self.wav_path)

        self.assertEqual("infant_cry_detected", result["status"])
        self.assertEqual(["infant_cry_evidence_strong"], result["reason_codes"])
        self.assertEqual("Infant-cry-like sound detected", result["label"])
        self.assertEqual(1.0, result["analyzed_duration_s"])
        self.assertEqual(1, result["analysis_view_count"])
        self.assertEqual("ast-audioset-baby-cry-v1", result["model_version"])
        self.assertEqual(0.04, result["_infant_score"])
        self.assertEqual(0.03, result["_generic_cry_score"])

    def test_strong_rule_rejects_score_below_absolute_boundary(self):
        with patch.object(
            cry_gate,
            "_event_scores",
            return_value=(0.039999, 0.001),
        ):
            result = cry_gate.classify(self.wav_path)

        self.assertEqual("cry_uncertain", result["status"])
        self.assertEqual(
            ["infant_cry_evidence_borderline"],
            result["reason_codes"],
        )

    def test_strong_rule_rejects_score_below_relative_boundary(self):
        with patch.object(
            cry_gate,
            "_event_scores",
            return_value=(0.04, 0.033334),
        ):
            result = cry_gate.classify(self.wav_path)

        self.assertEqual("cry_uncertain", result["status"])
        self.assertEqual(
            ["generic_cry_not_infant_specific"],
            result["reason_codes"],
        )

    def test_middle_band_abstains(self):
        with patch.object(cry_gate, "_event_scores", return_value=(0.03, 0.01)):
            result = cry_gate.classify(self.wav_path)

        self.assertEqual("cry_uncertain", result["status"])
        self.assertEqual(
            ["infant_cry_evidence_borderline"],
            result["reason_codes"],
        )
        self.assertIsNone(result["label"])

    def test_low_score_is_not_detected(self):
        with patch.object(
            cry_gate,
            "_event_scores",
            return_value=(0.024, 0.001),
        ):
            result = cry_gate.classify(self.wav_path)

        self.assertEqual("no_cry_detected", result["status"])
        self.assertEqual(["infant_cry_evidence_low"], result["reason_codes"])
        self.assertIsNone(result["label"])

    def test_generic_cry_dominance_abstains(self):
        with patch.object(cry_gate, "_event_scores", return_value=(0.08, 0.08)):
            result = cry_gate.classify(self.wav_path)

        self.assertEqual("cry_uncertain", result["status"])
        self.assertEqual(
            ["generic_cry_not_infant_specific"],
            result["reason_codes"],
        )

    def test_model_failure_is_fail_closed(self):
        with patch.object(
            cry_gate,
            "_event_scores",
            side_effect=RuntimeError("boom"),
        ):
            result = cry_gate.classify(self.wav_path)

        self.assertEqual("gate_unavailable", result["status"])
        self.assertEqual(
            ["cry_gate_model_unavailable"],
            result["reason_codes"],
        )
        self.assertIsNone(result["label"])

    def test_one_centered_view_is_limited_to_ten_seconds(self):
        long_path = Path(self.tempdir.name) / "long.wav"
        samples = np.arange(192000, dtype=np.int32)
        _write_wav(long_path, samples)

        with patch.object(
            cry_gate,
            "_event_scores",
            return_value=(0.024, 0.001),
        ) as score:
            result = cry_gate.classify(str(long_path))

        view = score.call_args.args[0]
        self.assertEqual(160000, view.size)
        np.testing.assert_allclose(
            np.asarray(samples[16000:176000], dtype=np.int16) / 32768.0,
            view,
        )
        self.assertEqual(10.0, result["analyzed_duration_s"])
        self.assertEqual(1, result["analysis_view_count"])


class CryGateInvalidAudioTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.root = Path(self.tempdir.name)

    def _assert_invalid_without_scoring(self, path: Path):
        with patch.object(cry_gate, "_event_scores") as score:
            result = cry_gate.classify(str(path))

        self.assertEqual("invalid_audio", result["status"])
        self.assertEqual(["cry_gate_invalid_audio"], result["reason_codes"])
        score.assert_not_called()

    def test_missing_file_is_invalid_without_model_inference(self):
        self._assert_invalid_without_scoring(self.root / "missing.wav")

    def test_non_wav_input_is_invalid_without_model_inference(self):
        path = self.root / "audio.mp3"
        path.write_bytes(b"not audio")
        self._assert_invalid_without_scoring(path)

    def test_empty_audio_is_invalid_without_model_inference(self):
        path = self.root / "empty.wav"
        _write_wav(path, np.array([], dtype=np.int16))
        self._assert_invalid_without_scoring(path)

    def test_wrong_sample_rate_is_invalid_without_model_inference(self):
        path = self.root / "eight-khz.wav"
        _write_wav(path, np.full(8000, 1000, dtype=np.int16), sample_rate=8000)
        self._assert_invalid_without_scoring(path)

    def test_stereo_audio_is_invalid_without_model_inference(self):
        path = self.root / "stereo.wav"
        stereo = np.tile(np.array([1000, -1000], dtype=np.int16), 16000)
        _write_wav(path, stereo, channels=2)
        self._assert_invalid_without_scoring(path)


class CryGateReadinessTests(unittest.TestCase):
    def test_readiness_reports_score_free_ready_state(self):
        with patch.object(cry_gate, "warm", return_value=True):
            result = cry_gate.readiness()

        self.assertEqual(
            {
                "ready": True,
                "model_version": "ast-audioset-baby-cry-v1",
            },
            result,
        )

    def test_readiness_fails_closed_without_model(self):
        with patch.object(cry_gate, "warm", return_value=False):
            result = cry_gate.readiness()

        self.assertEqual(
            {
                "ready": False,
                "model_version": "ast-audioset-baby-cry-v1",
            },
            result,
        )


if __name__ == "__main__":
    unittest.main()
