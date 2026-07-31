import contextlib
import io
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch


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

    def test_cry_gate_check_shows_cache_labels_and_version_when_runnable(self):
        from tools import doctor

        output = io.StringIO()
        with (
            patch(
                "src.cry_gate.readiness",
                return_value={
                    "ready": True,
                    "model_version": "ast-audioset-baby-cry-v1",
                },
            ),
            patch.object(doctor, "ok") as ok,
            contextlib.redirect_stdout(output),
        ):
            doctor.check_cry_gate(required=True)

        messages = [call.args[0] for call in ok.call_args_list]
        self.assertIn("cry gate model cached and runnable", messages)
        self.assertIn("target label present: Baby cry, infant cry", messages)
        self.assertIn(
            "cry gate model version ast-audioset-baby-cry-v1",
            messages,
        )

    def test_unavailable_cry_gate_blocks_only_requested_infant_care(self):
        from tools import doctor

        unavailable = {
            "ready": False,
            "model_version": "ast-audioset-baby-cry-v1",
        }
        with (
            patch("src.cry_gate.readiness", return_value=unavailable),
            patch.object(doctor, "fail") as fail,
            patch.object(doctor, "warn") as warn,
        ):
            doctor.check_cry_gate(required=True)
            fail.assert_called_once_with(
                "cry gate unavailable - requested infant care cannot start"
            )
            warn.assert_not_called()

        with (
            patch("src.cry_gate.readiness", return_value=unavailable),
            patch.object(doctor, "fail") as fail,
            patch.object(doctor, "warn") as warn,
        ):
            doctor.check_cry_gate(required=False)
            warn.assert_called_once_with(
                "cry gate unavailable - infant care is disabled"
            )
            fail.assert_not_called()

    def test_infant_care_flag_requests_blocking_gate_check(self):
        from tools import doctor

        doctor.FAILS = 0
        doctor.WARNS = 0
        with (
            patch.object(sys, "argv", ["doctor.py", "--infant-care", "baby-1"]),
            patch.object(doctor, "check_python"),
            patch.object(doctor, "check_deps"),
            patch.object(doctor, "check_modules", return_value=True),
            patch.object(doctor, "check_models"),
            patch.object(doctor, "check_cry_gate") as check_cry_gate,
            patch.object(doctor, "check_config"),
            patch.object(doctor, "check_storage_and_baseline") as storage,
            patch.object(doctor, "check_audio_device"),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            result = doctor.main()

        self.assertEqual(0, result)
        check_cry_gate.assert_called_once_with(required=True)
        storage.assert_called_once_with(["baby-1"])


class CryGateCachePortabilityTests(unittest.TestCase):
    def setUp(self):
        from src import cry_gate

        self.cry_gate = cry_gate
        self.original_extractor = cry_gate._EXTRACTOR
        self.original_model = cry_gate._MODEL
        cry_gate._EXTRACTOR = None
        cry_gate._MODEL = None
        self.addCleanup(self._restore_components)

    def _restore_components(self):
        self.cry_gate._EXTRACTOR = self.original_extractor
        self.cry_gate._MODEL = self.original_model

    def test_explicit_model_directory_wins_over_standard_hf_cache(self):
        with tempfile.TemporaryDirectory() as tempdir:
            configured = Path(tempdir) / "configured"
            standard = Path(tempdir) / "huggingface" / "hub"
            with (
                patch.dict(
                    os.environ,
                    {"IM_MODEL_DIR": str(configured)},
                    clear=False,
                ),
                patch.object(
                    self.cry_gate.config,
                    "MODEL_DIR",
                    str(configured),
                ),
                patch.object(
                    self.cry_gate,
                    "_huggingface_cache_dir",
                    return_value=standard,
                    create=True,
                ),
            ):
                cache_path = self.cry_gate._model_cache_dir()

        self.assertEqual(configured.resolve(), cache_path.resolve())

    def test_default_model_directory_reuses_standard_hf_cache(self):
        with tempfile.TemporaryDirectory() as tempdir:
            standard = Path(tempdir) / "huggingface" / "hub"
            with (
                patch.dict(
                    os.environ,
                    {"IM_MODEL_DIR": ""},
                    clear=False,
                ),
                patch.object(
                    self.cry_gate,
                    "_huggingface_cache_dir",
                    return_value=standard,
                    create=True,
                ),
            ):
                cache_path = self.cry_gate._model_cache_dir()

        self.assertEqual(standard.resolve(), cache_path.resolve())

    def test_cry_gate_loading_does_not_require_privileged_symlinks(self):
        labels = {
            0: "Baby cry, infant cry",
            1: "Crying, sobbing",
        }
        extractor = object()
        model = SimpleNamespace(config=SimpleNamespace(id2label=labels))
        model.eval = Mock()
        extractor_loader = Mock(return_value=extractor)
        model_loader = Mock(return_value=model)
        fake_transformers = SimpleNamespace(
            AutoFeatureExtractor=SimpleNamespace(from_pretrained=extractor_loader),
            AutoModelForAudioClassification=SimpleNamespace(
                from_pretrained=model_loader
            ),
        )

        with (
            tempfile.TemporaryDirectory() as tempdir,
            patch.dict(
                os.environ,
                {"IM_MODEL_DIR": tempdir},
                clear=False,
            ),
            patch.object(self.cry_gate.config, "MODEL_DIR", tempdir),
            patch.dict(sys.modules, {"transformers": fake_transformers}),
            patch.object(
                os,
                "symlink",
                side_effect=PermissionError("symlinks need elevation"),
            ),
        ):
            loaded_extractor, loaded_model = self.cry_gate._load_components()

        self.assertIs(extractor, loaded_extractor)
        self.assertIs(model, loaded_model)
        expected_cache = str(Path(tempdir))
        self.assertEqual(
            expected_cache,
            extractor_loader.call_args.kwargs["cache_dir"],
        )
        self.assertTrue(
            extractor_loader.call_args.kwargs["local_files_only"],
        )
        self.assertEqual(
            expected_cache,
            model_loader.call_args.kwargs["cache_dir"],
        )
        self.assertTrue(
            model_loader.call_args.kwargs["local_files_only"],
        )

    def test_cry_gate_load_falls_back_to_download_when_cache_is_empty(self):
        labels = {
            0: "Baby cry, infant cry",
            1: "Crying, sobbing",
        }
        extractor = object()
        model = SimpleNamespace(config=SimpleNamespace(id2label=labels))
        model.eval = Mock()
        extractor_loader = Mock(
            side_effect=[OSError("not cached"), extractor],
        )
        model_loader = Mock(
            side_effect=[OSError("not cached"), model],
        )
        fake_transformers = SimpleNamespace(
            AutoFeatureExtractor=SimpleNamespace(from_pretrained=extractor_loader),
            AutoModelForAudioClassification=SimpleNamespace(
                from_pretrained=model_loader
            ),
        )

        with (
            tempfile.TemporaryDirectory() as tempdir,
            patch.dict(
                os.environ,
                {"IM_MODEL_DIR": tempdir},
                clear=False,
            ),
            patch.object(self.cry_gate.config, "MODEL_DIR", tempdir),
            patch.dict(sys.modules, {"transformers": fake_transformers}),
        ):
            loaded_extractor, loaded_model = self.cry_gate._load_components()

        self.assertIs(extractor, loaded_extractor)
        self.assertIs(model, loaded_model)
        self.assertTrue(
            extractor_loader.call_args_list[0].kwargs["local_files_only"]
        )
        self.assertFalse(
            extractor_loader.call_args_list[1].kwargs["local_files_only"]
        )
        self.assertTrue(
            model_loader.call_args_list[0].kwargs["local_files_only"]
        )
        self.assertFalse(
            model_loader.call_args_list[1].kwargs["local_files_only"]
        )


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
