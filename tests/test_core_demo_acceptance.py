"""Focused tests for the controlled real-audio acceptance runner."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from src import cry_gate, encoders, identity
from tools import core_demo_acceptance


class CoreDemoAcceptanceTests(unittest.TestCase):
    def test_minimum_listening_window_uses_audio_time(self):
        self.assertFalse(
            core_demo_acceptance._meets_minimum_listening_window(6, 3)
        )
        self.assertTrue(
            core_demo_acceptance._meets_minimum_listening_window(7, 3)
        )

    def test_warm_models_rejects_unavailable_infant_encoder(self):
        encoder = identity.ENCODER_FOR_KIND[identity.KIND_INFANT]
        with (
            patch.object(encoders, "warm", return_value={encoder: False}),
            patch.object(cry_gate, "warm", return_value=True),
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "infant identity encoder is unavailable",
            ):
                core_demo_acceptance._warm_models()


if __name__ == "__main__":
    unittest.main()
