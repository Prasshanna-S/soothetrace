import os
import unittest
from tempfile import TemporaryDirectory
from unittest.mock import patch


class RecordTests(unittest.TestCase):
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
