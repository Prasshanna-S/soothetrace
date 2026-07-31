import math
import tempfile
import unittest
import wave
from pathlib import Path

import numpy as np

from src import audio_duplicate


def _write(path: Path, samples: np.ndarray, sample_rate: int = 16000):
    pcm = np.clip(samples, -1.0, 1.0)
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(np.round(pcm * 32767.0).astype("<i2").tobytes())


class AudioDuplicateTests(unittest.TestCase):
    def test_level_changed_copy_is_near_duplicate(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            time = np.arange(16000 * 3) / 16000
            envelope = 0.2 + 0.8 * np.square(np.sin(2 * np.pi * 1.3 * time))
            source = envelope * np.sin(2 * np.pi * (310 + 45 * time) * time)
            first = root / "first.wav"
            second = root / "second.wav"
            _write(first, source * 0.7)
            _write(second, source * 0.35)

            a = audio_duplicate.signature(first)
            b = audio_duplicate.signature(second)
            self.assertIsNotNone(a)
            self.assertIsNotNone(b)
            self.assertTrue(audio_duplicate.is_near_duplicate(a, b))

    def test_different_temporal_pattern_is_not_duplicate(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            time = np.arange(16000 * 3) / 16000
            first_signal = (
                (time < 1.2).astype(float)
                * np.sin(2 * np.pi * 310 * time)
            )
            second_signal = (
                (time > 1.8).astype(float)
                * np.sin(2 * np.pi * 520 * time)
            )
            first = root / "first.wav"
            second = root / "second.wav"
            _write(first, first_signal * 0.5)
            _write(second, second_signal * 0.5)

            a = audio_duplicate.signature(first)
            b = audio_duplicate.signature(second)
            self.assertFalse(audio_duplicate.is_near_duplicate(a, b))

    def test_short_or_invalid_audio_has_no_signature(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            short = root / "short.wav"
            _write(short, np.zeros(100))
            self.assertIsNone(audio_duplicate.signature(short))
            self.assertIsNone(audio_duplicate.signature(root / "missing.wav"))


if __name__ == "__main__":
    unittest.main()
