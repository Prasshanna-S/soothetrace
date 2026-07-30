import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from src import speech


class SpeechContractStubTests(unittest.TestCase):
    def test_contract_stubs_return_safe_empty_values(self):
        try:
            from src import speech
        except ImportError:
            self.fail("src.speech must implement the frozen speech contract")

        self.assertEqual(speech.transcribe("missing.wav"), "")
        self.assertEqual(
            speech.extract_interventions(""),
            [],
        )
        self.assertIsNone(speech.infer_outcome("", []))


class TranscribeTests(unittest.TestCase):
    def test_transcribe_returns_provider_text_for_raw_audio_file(self):
        class FakeTranscriptions:
            def create(self, **kwargs):
                self.kwargs = kwargs
                return SimpleNamespace(text="I offered her a bottle.")

        transcriptions = FakeTranscriptions()
        client = SimpleNamespace(
            audio=SimpleNamespace(transcriptions=transcriptions),
        )

        with TemporaryDirectory() as directory:
            audio_path = Path(directory) / "mixture.wav"
            audio_path.write_bytes(b"raw caregiver and infant mixture")

            with patch.object(
                speech,
                "_get_client",
                return_value=client,
                create=True,
            ):
                result = speech.transcribe(str(audio_path))

        self.assertEqual(result, "I offered her a bottle.")
        self.assertEqual(
            transcriptions.kwargs["model"],
            speech.config.TRANSCRIBE_MODEL,
        )

    def test_transcribe_uses_local_whisper_when_offline(self):
        def fake_run(command, **kwargs):
            output_dir = command[command.index("--output_dir") + 1]
            audio_path = command[1]
            transcript_path = Path(output_dir) / f"{Path(audio_path).stem}.txt"
            transcript_path.write_text("Local caregiver transcript.\n")
            return SimpleNamespace(returncode=0, stderr="")

        with TemporaryDirectory() as directory:
            audio_path = Path(directory) / "mixture.wav"
            audio_path.write_bytes(b"raw caregiver and infant mixture")

            with (
                patch.object(speech.config, "OFFLINE", True),
                patch.object(
                    speech,
                    "_get_client",
                    side_effect=AssertionError("offline mode must not use network"),
                ),
                patch.object(speech.subprocess, "run", side_effect=fake_run),
            ):
                result = speech.transcribe(str(audio_path))

        self.assertEqual(result, "Local caregiver transcript.")

    def test_offline_whisper_failure_does_not_log_a_subprocess_traceback(self):
        with TemporaryDirectory() as directory:
            audio_path = Path(directory) / "mixture.wav"
            audio_path.write_bytes(b"raw caregiver and infant mixture")
            failure = SimpleNamespace(
                returncode=1,
                stderr=(
                    "Traceback (most recent call last):\n"
                    "  File \"whisper.py\", line 1\n"
                    "PermissionError: model unavailable"
                ),
            )

            with (
                patch.object(speech.subprocess, "run", return_value=failure),
                self.assertLogs(speech.logger, level="ERROR") as captured,
            ):
                result = speech._transcribe_offline(str(audio_path))

        self.assertEqual(result, "")
        self.assertNotIn("Traceback", "\n".join(captured.output))
        self.assertIn("PermissionError: model unavailable", captured.output[-1])


class ExtractInterventionsTests(unittest.TestCase):
    def test_reason_json_uses_json_mode_compatible_input(self):
        class FakeResponses:
            def create(self, **kwargs):
                if "json" not in kwargs["input"].casefold():
                    raise ValueError("input must mention JSON")
                return SimpleNamespace(output_text='{"interventions":[]}')

        client = SimpleNamespace(responses=FakeResponses())
        with patch.object(speech, "_get_client", return_value=client):
            result = speech._reason_json("Return structured data.", "transcript")

        self.assertEqual(result, {"interventions": []})

    def test_extract_keeps_only_actions_with_literal_transcript_evidence(self):
        transcript = "I checked her diaper, then I offered a bottle."
        provider_json = {
            "interventions": [
                {
                    "order": 8,
                    "action": "offered bottle",
                    "evidence": "offered a bottle",
                },
                {
                    "order": 2,
                    "action": "checked diaper",
                    "evidence": "checked her diaper",
                },
                {
                    "order": 3,
                    "action": "used white noise",
                    "evidence": "turned on white noise",
                },
            ],
        }

        with patch.object(
            speech,
            "_reason_json",
            return_value=provider_json,
            create=True,
        ):
            result = speech.extract_interventions(transcript)

        self.assertEqual(
            result,
            [
                {
                    "order": 1,
                    "action": "checked diaper",
                    "evidence": "checked her diaper",
                },
                {
                    "order": 2,
                    "action": "offered bottle",
                    "evidence": "offered a bottle",
                },
            ],
        )

    def test_offline_extracts_ordered_literal_intervention_spans_without_network(self):
        transcript = (
            "I checked her diaper, then I walked with her, and finally offered a bottle."
        )

        with (
            patch.object(speech.config, "OFFLINE", True),
            patch.object(
                speech,
                "_reason_json",
                side_effect=AssertionError("offline extraction must not call a provider"),
            ),
        ):
            result = speech.extract_interventions(transcript)

        self.assertEqual(
            [
                {
                    "order": 1,
                    "action": "checked diaper",
                    "evidence": "checked her diaper",
                },
                {
                    "order": 2,
                    "action": "walked",
                    "evidence": "walked with",
                },
                {
                    "order": 3,
                    "action": "offered feeding",
                    "evidence": "offered a bottle",
                },
            ],
            result,
        )

    def test_offline_omits_negated_and_unsupported_actions(self):
        transcript = (
            "I did not try a bottle. I wondered whether she was hungry, "
            "but I never used the pacifier."
        )

        with (
            patch.object(speech.config, "OFFLINE", True),
            patch.object(
                speech,
                "_reason_json",
                side_effect=AssertionError("offline extraction must not call a provider"),
            ),
        ):
            result = speech.extract_interventions(transcript)

        self.assertEqual([], result)

    def test_online_extraction_falls_back_to_deterministic_grounded_evidence(self):
        transcript = "I rocked her and she calmed down."

        with (
            patch.object(speech.config, "OFFLINE", False),
            patch.object(speech, "_reason_json", return_value=None),
        ):
            result = speech.extract_interventions(transcript)

        self.assertEqual(
            [{"order": 1, "action": "rocked", "evidence": "rocked"}],
            result,
        )

    def test_offline_recognizes_plain_feeding_without_naming_a_container(self):
        with patch.object(speech.config, "OFFLINE", True):
            result = speech.extract_interventions("I fed her and waited.")

        self.assertEqual(
            [{"order": 1, "action": "offered feeding", "evidence": "fed her"}],
            result,
        )


class InferOutcomeTests(unittest.TestCase):
    def test_infer_outcome_requires_literal_evidence_and_boolean_worked(self):
        transcript = "After the bottle, she settled right down."
        provider_json = {
            "outcome": "she settled right down",
            "worked": True,
            "evidence": "she settled right down",
        }

        with patch.object(speech, "_reason_json", return_value=provider_json):
            result = speech.infer_outcome(transcript, [])

        self.assertEqual(
            result,
            {"outcome": "she settled right down", "worked": True},
        )

    def test_infer_outcome_returns_none_when_evidence_is_not_in_transcript(self):
        provider_json = {
            "outcome": "rocking worked",
            "worked": True,
            "evidence": "rocking worked",
        }

        with patch.object(speech, "_reason_json", return_value=provider_json):
            result = speech.infer_outcome("I tried a bottle.", [])

        self.assertIsNone(result)

    def test_offline_infers_positive_outcome_from_literal_span(self):
        transcript = "I walked with her and she settled down."
        interventions = [
            {"order": 1, "action": "walked", "evidence": "walked with"}
        ]

        with (
            patch.object(speech.config, "OFFLINE", True),
            patch.object(
                speech,
                "_reason_json",
                side_effect=AssertionError("offline outcome must not call a provider"),
            ),
        ):
            result = speech.infer_outcome(transcript, interventions)

        self.assertEqual({"outcome": "settled down", "worked": True}, result)

    def test_offline_uses_last_explicit_negative_outcome(self):
        transcript = "The bottle did not work; she is still crying."
        interventions = [
            {"order": 1, "action": "offered feeding", "evidence": "bottle"}
        ]

        with (
            patch.object(speech.config, "OFFLINE", True),
            patch.object(
                speech,
                "_reason_json",
                side_effect=AssertionError("offline outcome must not call a provider"),
            ),
        ):
            result = speech.infer_outcome(transcript, interventions)

        self.assertEqual({"outcome": "still crying", "worked": False}, result)

    def test_offline_outcome_after_final_intervention_wins(self):
        transcript = (
            "She settled down earlier. Then I picked her up, but she is still crying."
        )
        interventions = [
            {"order": 1, "action": "held", "evidence": "picked her up"}
        ]

        with (
            patch.object(speech.config, "OFFLINE", True),
            patch.object(
                speech,
                "_reason_json",
                side_effect=AssertionError("offline outcome must not call a provider"),
            ),
        ):
            result = speech.infer_outcome(transcript, interventions)

        self.assertEqual({"outcome": "still crying", "worked": False}, result)

    def test_offline_ambiguous_outcome_returns_none(self):
        transcript = "I held her and waited for a while."
        interventions = [{"order": 1, "action": "held", "evidence": "held"}]

        with (
            patch.object(speech.config, "OFFLINE", True),
            patch.object(
                speech,
                "_reason_json",
                side_effect=AssertionError("offline outcome must not call a provider"),
            ),
        ):
            result = speech.infer_outcome(transcript, interventions)

        self.assertIsNone(result)

    def test_offline_recognizes_plain_settled_as_positive_outcome(self):
        transcript = "I held him for a while and then he settled."
        interventions = [{"order": 1, "action": "held", "evidence": "held"}]

        with patch.object(speech.config, "OFFLINE", True):
            result = speech.infer_outcome(transcript, interventions)

        self.assertEqual({"outcome": "settled", "worked": True}, result)


if __name__ == "__main__":
    unittest.main()
