import os
import unittest
from tempfile import TemporaryDirectory
from unittest.mock import patch


class RecordTests(unittest.TestCase):
    def test_capture_input_uses_directshow_for_a_named_windows_device(self):
        from src import session

        with patch.object(session.platform, "system", return_value="Windows"):
            arguments = session._capture_input_args("Microphone Array (USB)")

        self.assertEqual(
            ["-f", "dshow", "-i", "audio=Microphone Array (USB)"],
            arguments,
        )

    def test_capture_input_keeps_the_existing_macos_default(self):
        from src import session

        with patch.object(session.platform, "system", return_value="Darwin"):
            arguments = session._capture_input_args()

        self.assertEqual(["-f", "avfoundation", "-i", ":0"], arguments)

    def test_capture_input_uses_alsa_default_on_linux(self):
        from src import session

        with patch.object(session.platform, "system", return_value="Linux"):
            arguments = session._capture_input_args()

        self.assertEqual(["-f", "alsa", "-i", "default"], arguments)

    def test_windows_cli_capture_requires_an_explicit_device(self):
        from src import session

        with (
            patch.object(session.platform, "system", return_value="Windows"),
            patch.dict(os.environ, {}, clear=True),
        ):
            self.assertFalse(session._capture_wav("capture.wav", 1.0))

    def test_record_returns_created_wav_in_configured_audio_directory(self):
        try:
            from src import session
        except ImportError:
            self.fail("src.session must implement the frozen session contract")

        def fake_capture(path, seconds):
            self.assertEqual(seconds, 1.5)
            with open(path, "wb") as wav:
                wav.write(b"RIFF-test-wave")
            return True

        with TemporaryDirectory() as directory:
            with (
                patch.object(session.config, "AUDIO_DIR", directory),
                patch.object(
                    session,
                    "_capture_wav",
                    side_effect=fake_capture,
                    create=True,
                ),
            ):
                result = session.record("baby/01", seconds=1.5)

            self.assertTrue(os.path.isfile(result))
            self.assertEqual(os.path.dirname(result), directory)
            self.assertTrue(os.path.basename(result).startswith("baby-01-"))


class FinishTests(unittest.TestCase):
    def test_typed_caregiver_follow_up_is_labeled_and_can_ground_actions(self):
        from src import session

        with TemporaryDirectory() as directory:
            audio_path = os.path.join(directory, "mixture.wav")
            with open(audio_path, "wb") as audio:
                audio.write(b"RIFF-test-wave")
            db_path = os.path.join(directory, "episodes.db")
            interventions = [
                {
                    "order": 1,
                    "action": "rocked",
                    "evidence": "rocked",
                }
            ]

            with (
                patch.object(
                    session.fingerprint,
                    "compute_windowed",
                    return_value=[0.0] * 87,
                ),
                patch.object(session.fingerprint, "duration_s", return_value=4.25),
                patch.object(
                    session.speech,
                    "transcribe",
                    return_value="The baby was crying.",
                ),
                patch.object(
                    session.speech,
                    "extract_interventions",
                    return_value=interventions,
                ) as extract,
            ):
                result = session.finish(
                    "profile-7",
                    audio_path,
                    caregiver_answer="I rocked the baby and she settled.",
                    db_path=db_path,
                )

        evidence_text = extract.call_args.args[0]
        self.assertIn("Audio transcript: The baby was crying.", evidence_text)
        self.assertIn(
            "Typed caregiver follow-up: I rocked the baby and she settled.",
            evidence_text,
        )
        self.assertEqual(evidence_text, result["transcript"])
        self.assertEqual(interventions, result["interventions"])
        self.assertEqual("caregiver", result["outcome_src"])
        self.assertIs(result["worked"], True)

    def test_finish_persists_supplied_incident_context_in_the_initial_insert(self):
        from src import session

        with TemporaryDirectory() as directory:
            audio_path = os.path.join(directory, "mixture.wav")
            with open(audio_path, "wb") as audio:
                audio.write(b"RIFF-test-wave")
            db_path = os.path.join(directory, "episodes.db")
            supplied_context = {
                "hour_local": 3,
                "tags": ["evening"],
                "identity_attempt_id": 91,
                "profile_id": 7,
            }

            with (
                patch.object(
                    session.fingerprint,
                    "compute_windowed",
                    return_value=[0.0] * 87,
                ),
                patch.object(session.fingerprint, "duration_s", return_value=4.25),
                patch.object(session.speech, "transcribe", return_value=""),
                patch.object(session.speech, "extract_interventions", return_value=[]),
                patch.object(session.speech, "infer_outcome", return_value=None),
            ):
                result = session.finish(
                    "profile-7",
                    audio_path,
                    caregiver_answer=None,
                    db_path=db_path,
                    context_override=supplied_context,
                )

        self.assertIsInstance(result.get("id"), int)
        self.assertEqual(supplied_context, result["context"])

    def test_finish_uses_the_explicit_database_for_every_episode_operation(self):
        from src import session

        with TemporaryDirectory() as directory:
            audio_path = os.path.join(directory, "mixture.wav")
            with open(audio_path, "wb") as audio:
                audio.write(b"RIFF-test-wave")
            explicit_db = os.path.join(directory, "explicit.db")
            default_db = os.path.join(directory, "default.db")

            with (
                patch.object(session.store.config, "DB_PATH", default_db),
                patch.object(session.store.config, "AUDIO_DIR", directory),
                patch.object(
                    session.fingerprint,
                    "compute_windowed",
                    return_value=[0.0] * 87,
                ),
                patch.object(session.fingerprint, "duration_s", return_value=4.25),
                patch.object(session.speech, "transcribe", return_value=""),
                patch.object(session.speech, "extract_interventions", return_value=[]),
                patch.object(session.speech, "infer_outcome", return_value=None),
            ):
                result = session.finish(
                    "profile-7",
                    audio_path,
                    caregiver_answer=None,
                    db_path=explicit_db,
                )

                explicit_rows = session.store.list_episodes("profile-7", explicit_db)
                default_rows = session.store.list_episodes("profile-7", default_db)

        self.assertIsInstance(result.get("id"), int)
        self.assertEqual(1, len(explicit_rows))
        self.assertEqual([], default_rows)

    def test_finish_records_explicit_negative_caregiver_outcome(self):
        from src import session

        self.assertTrue(
            hasattr(session, "finish"),
            "src.session.finish must implement the frozen session contract",
        )
        fingerprint = [float(index) for index in range(87)]
        interventions = [
            {
                "order": 1,
                "action": "offered bottle",
                "evidence": "offered a bottle",
            }
        ]

        with TemporaryDirectory() as directory:
            audio_path = os.path.join(directory, "mixture.wav")
            with open(audio_path, "wb") as audio:
                audio.write(b"RIFF-test-wave")
            db_path = os.path.join(directory, "episodes.db")

            with (
                patch.object(session.store.config, "DB_PATH", db_path),
                patch.object(session.store.config, "AUDIO_DIR", directory),
                patch.object(
                    session.fingerprint,
                    "compute_windowed",
                    return_value=fingerprint,
                ),
                patch.object(session.fingerprint, "duration_s", return_value=4.25),
                patch.object(
                    session.speech,
                    "transcribe",
                    return_value="I offered a bottle.",
                ),
                patch.object(
                    session.speech,
                    "extract_interventions",
                    return_value=interventions,
                ),
            ):
                result = session.finish(
                    "baby-01",
                    audio_path,
                    caregiver_answer="Nothing worked; she cried herself out.",
                )

        self.assertIsInstance(result["id"], int)
        self.assertEqual(result["fingerprint"], fingerprint)
        self.assertEqual(result["interventions"], interventions)
        self.assertEqual(
            result["outcome"],
            "Nothing worked; she cried herself out.",
        )
        self.assertEqual(result["outcome_src"], "caregiver")
        self.assertIs(result["worked"], False)

    def test_finish_records_explicit_positive_caregiver_outcome(self):
        from src import session

        with TemporaryDirectory() as directory:
            audio_path = os.path.join(directory, "mixture.wav")
            with open(audio_path, "wb") as audio:
                audio.write(b"RIFF-test-wave")
            db_path = os.path.join(directory, "episodes.db")

            with (
                patch.object(session.store.config, "DB_PATH", db_path),
                patch.object(session.store.config, "AUDIO_DIR", directory),
                patch.object(
                    session.fingerprint,
                    "compute_windowed",
                    return_value=[0.0] * 87,
                ),
                patch.object(session.fingerprint, "duration_s", return_value=4.25),
                patch.object(session.speech, "transcribe", return_value=""),
                patch.object(
                    session.speech,
                    "extract_interventions",
                    return_value=[],
                ),
            ):
                result = session.finish(
                    "baby-01",
                    audio_path,
                    caregiver_answer="Feeding him worked.",
                )

        self.assertIs(result["worked"], True)


if __name__ == "__main__":
    unittest.main()
