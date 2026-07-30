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


class StructuredFinishTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.audio_path = os.path.join(self.tempdir.name, "selected.wav")
        with open(self.audio_path, "wb") as audio:
            audio.write(b"RIFF-selected-care-segment")
        self.db_path = os.path.join(self.tempdir.name, "episodes.db")
        self.started_at = "2026-07-30T03:14:15-04:00"

    def _finish(self, **overrides):
        from src import session

        audio_transcript = overrides.pop("_audio_transcript", "I picked her up.")
        extracted_interventions = overrides.pop(
            "_extracted_interventions",
            [
                {
                    "order": 9,
                    "action": "picked her up",
                    "evidence": "I picked her up.",
                },
                {
                    "order": 10,
                    "action": "Held baby upright.",
                    "evidence": "Held baby upright.",
                },
            ],
        )
        arguments = {
            "subject_id": "profile-7",
            "audio_path": self.audio_path,
            "action": "Held baby upright.",
            "settled": True,
            "notes": "Settled in two minutes.",
            "started_at": self.started_at,
            "db_path": self.db_path,
            "context_override": {
                "hour_local": 3,
                "tags": ["evening"],
                "care_session_id": 41,
                "selected_chunk_id": 73,
                "profile_id": 7,
            },
        }
        arguments.update(overrides)
        with (
            patch.object(
                session.fingerprint,
                "compute_windowed",
                return_value=[0.0] * 87,
            ),
            patch.object(session.fingerprint, "duration_s", return_value=6.5),
            patch.object(
                session.speech,
                "transcribe",
                return_value=audio_transcript,
            ) as transcribe,
            patch.object(
                session.speech,
                "extract_interventions",
                return_value=extracted_interventions,
            ),
        ):
            result = session.finish_structured(**arguments)
        return result, transcribe

    def test_structured_finish_requires_a_trimmed_action_within_500_characters(self):
        for action in (None, "", "   ", "x" * 501):
            with self.subTest(action=action):
                result, transcribe = self._finish(action=action)
                self.assertEqual({}, result)
                transcribe.assert_not_called()

        result, _ = self._finish(action="  Held baby upright.  ")

        self.assertEqual("Held baby upright.", result["interventions"][-1]["action"])
        self.assertEqual("Held baby upright.", result["interventions"][-1]["evidence"])

    def test_structured_finish_accepts_settled_by_exact_type_only(self):
        for settled in (0, 1, "yes", [], {}):
            with self.subTest(settled=settled):
                result, transcribe = self._finish(settled=settled)
                self.assertEqual({}, result)
                transcribe.assert_not_called()

        for settled in (True, False, None):
            with self.subTest(settled=settled):
                result, _ = self._finish(settled=settled)
                self.assertIs(result["worked"], settled)

    def test_structured_finish_rejects_invalid_or_overlong_notes(self):
        for notes in (7, "x" * 1001):
            with self.subTest(notes=notes):
                result, transcribe = self._finish(notes=notes)
                self.assertEqual({}, result)
                transcribe.assert_not_called()

        result, _ = self._finish(notes="  Settled in two minutes.  ")

        self.assertEqual(
            "The baby settled. Settled in two minutes.",
            result["outcome"],
        )

    def test_structured_finish_keeps_source_labels_literal_evidence_and_chunk_time(self):
        result, transcribe = self._finish()

        self.assertEqual(self.started_at, result["started_at"])
        self.assertEqual(
            {
                "hour_local": 3,
                "tags": ["evening"],
                "care_session_id": 41,
                "selected_chunk_id": 73,
                "profile_id": 7,
            },
            result["context"],
        )
        self.assertEqual(
            "Audio transcript: I picked her up.\n"
            "Typed caregiver follow-up: Action: Held baby upright. "
            "Settled: yes. Notes: Settled in two minutes.",
            result["transcript"],
        )
        self.assertEqual(
            [
                {
                    "order": 1,
                    "action": "picked her up",
                    "evidence": "I picked her up.",
                },
                {
                    "order": 2,
                    "action": "Held baby upright.",
                    "evidence": "Held baby upright.",
                },
            ],
            result["interventions"],
        )
        self.assertEqual("caregiver", result["outcome_src"])
        transcribe.assert_called_once_with(self.audio_path)

    def test_structured_finish_moves_an_earlier_exact_duplicate_to_the_end(self):
        result, _ = self._finish(
            _extracted_interventions=[
                {
                    "order": 7,
                    "action": "Held baby upright.",
                    "evidence": "Held baby upright.",
                },
                {
                    "order": 8,
                    "action": "picked her up",
                    "evidence": "I picked her up.",
                },
                {
                    "order": 9,
                    "action": "dimmed the lights",
                    "evidence": "I dimmed the lights.",
                },
            ]
        )

        self.assertEqual(
            [
                {
                    "order": 1,
                    "action": "picked her up",
                    "evidence": "I picked her up.",
                },
                {
                    "order": 2,
                    "action": "dimmed the lights",
                    "evidence": "I dimmed the lights.",
                },
                {
                    "order": 3,
                    "action": "Held baby upright.",
                    "evidence": "Held baby upright.",
                },
            ],
            result["interventions"],
        )

    def test_structured_finish_maps_each_settled_state_without_truthiness(self):
        expected = {
            True: "The baby settled.",
            False: "The baby did not settle.",
            None: "Whether the baby settled was not recorded.",
        }
        for settled, outcome in expected.items():
            with self.subTest(settled=settled):
                result, _ = self._finish(settled=settled, notes=None)
                self.assertIs(result["worked"], settled)
                self.assertEqual(outcome, result["outcome"])

    def test_structured_finish_does_not_invent_an_automatic_transcript(self):
        result, _ = self._finish(_audio_transcript="")

        self.assertNotIn("Audio transcript:", result["transcript"])
        self.assertEqual(
            "Typed caregiver follow-up: Action: Held baby upright. "
            "Settled: yes. Notes: Settled in two minutes.",
            result["transcript"],
        )

    def test_structured_finish_returns_no_episode_id_when_save_fails(self):
        from src import session

        with patch.object(session.store, "save_episode", return_value=0):
            result, transcribe = self._finish()

        self.assertIsNone(result.get("id"))
        transcribe.assert_called_once_with(self.audio_path)
        self.assertEqual([], session.store.list_episodes("profile-7", self.db_path))


if __name__ == "__main__":
    unittest.main()
