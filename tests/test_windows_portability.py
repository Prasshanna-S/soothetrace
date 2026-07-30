import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


class EncoderCacheTests(unittest.TestCase):
    def test_speechbrain_model_cache_uses_copy_instead_of_privileged_symlinks(self):
        from speechbrain.utils.fetching import LocalStrategy
        from src import encoders

        encoder_name = encoders.ECAPA_ADULT
        encoders._loaded.pop(encoder_name, None)
        sentinel = object()
        with patch(
            "speechbrain.inference.speaker.EncoderClassifier.from_hparams",
            return_value=sentinel,
        ) as load:
            result = encoders._load(encoder_name)
        self.addCleanup(encoders._loaded.pop, encoder_name, None)

        self.assertIs(sentinel, result)
        self.assertIs(LocalStrategy.COPY, load.call_args.kwargs["local_strategy"])


class DoctorTests(unittest.TestCase):
    def test_directshow_device_parser_returns_only_audio_devices(self):
        from tools import doctor

        output = """
[dshow @ 000001] "Integrated Camera" (video)
[dshow @ 000001] "Microphone Array (USB Audio)" (audio)
[dshow @ 000001]   Alternative name "@device_cm_{123}"
[dshow @ 000001] "Line In (Realtek Audio)" (audio)
"""

        self.assertEqual(
            ["Microphone Array (USB Audio)", "Line In (Realtek Audio)"],
            doctor._audio_devices_from_ffmpeg("Windows", output),
        )

    def test_torch_and_torchaudio_versions_require_compatible_local_builds(self):
        from tools import doctor

        self.assertTrue(doctor._matching_torch_versions("2.6.0+cpu", "2.6.0+cpu"))
        self.assertFalse(doctor._matching_torch_versions("2.7.0", "2.6.0+cpu"))
        self.assertFalse(doctor._matching_torch_versions("2.6.0+cpu", "2.6.0+cu124"))


class CertificatePortabilityTests(unittest.TestCase):
    def test_existing_phone_certificate_must_still_be_current(self):
        from spikes.mobile_capture.certificates import (
            generate_certificates,
            server_certificate_matches_ip,
        )

        class AfterExpiry:
            @classmethod
            def now(cls, tz=None):
                return datetime.now(tz) + timedelta(days=31)

        with tempfile.TemporaryDirectory() as tempdir:
            certificate = generate_certificates(
                "192.168.50.23",
                Path(tempdir),
            ).server_certificate
            with patch("spikes.mobile_capture.certificates.datetime", AfterExpiry):
                self.assertFalse(
                    server_certificate_matches_ip(
                        certificate,
                        "192.168.50.23",
                    )
                )


class WindowsLauncherContractTests(unittest.TestCase):
    def test_setup_always_builds_the_required_infant_baseline(self):
        setup = (ROOT / "scripts" / "setup_windows.ps1").read_text(encoding="utf-8")

        self.assertNotIn("SkipBaseline", setup)
        self.assertIn("& $PythonPath $BaselineScript", setup)

    def test_setup_rejects_mismatched_torch_local_builds(self):
        setup = (ROOT / "scripts" / "setup_windows.ps1").read_text(encoding="utf-8")

        self.assertNotIn("torch.__version__.split('+')[0]", setup)
        self.assertIn("torch.__version__ == torchaudio.__version__", setup)

    def test_phone_launcher_rejects_a_certificate_for_an_old_lan_ip(self):
        launcher = (ROOT / "scripts" / "run_windows.ps1").read_text(encoding="utf-8")

        self.assertIn("--check-existing", launcher)
        self.assertIn("does not contain the current LAN IP", launcher)

    def test_windows_workflow_executes_launchers_and_platform_regressions(self):
        workflow = (
            ROOT / ".github" / "workflows" / "windows-backend.yml"
        ).read_text(encoding="utf-8")
        steps = workflow.split("\n      - name: ")

        for launcher in (
            r".\scripts\setup_windows.ps1",
            r".\scripts\run_windows.ps1",
        ):
            self.assertTrue(
                any(
                    launcher in step and "shell: powershell" in step
                    for step in steps
                ),
                f"{launcher} must execute under Windows PowerShell 5.1",
            )
        self.assertIn("tests.test_windows_portability", workflow)
        self.assertIn("tests.test_product_session", workflow)
        self.assertIn("tests.test_product_render", workflow)
        self.assertIn("tests.test_mobile_capture_spike", workflow)

    def test_windows_smoke_requires_a_fully_ready_backend(self):
        smoke = (ROOT / "tests" / "test_windows_backend_smoke.py").read_text(
            encoding="utf-8"
        )

        self.assertIn('self.assertEqual("ready", health["status"], health)', smoke)
        self.assertIn('self.assertTrue(health["population_baseline"], health)', smoke)
        self.assertIn('self.assertTrue(health["encoders"]["infant"], health)', smoke)
        self.assertIn(
            'self.assertTrue(health["encoders"]["human_imitation"], health)',
            smoke,
        )


if __name__ == "__main__":
    unittest.main()
