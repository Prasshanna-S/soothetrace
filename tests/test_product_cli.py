import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from types import SimpleNamespace
from unittest.mock import patch


class CliTests(unittest.TestCase):
    def test_record_command_prints_the_created_audio_path(self):
        try:
            from src import cli
        except ImportError:
            self.fail("src.cli must implement the operator commands")

        output = io.StringIO()
        with (
            patch.object(cli.session, "record", return_value="/tmp/baby.wav"),
            patch.object(cli.store, "list_episodes", return_value=[{"id": 1}]),
            redirect_stdout(output),
        ):
            code = cli.main(["record", "baby-01", "--seconds", "1.0"])

        self.assertEqual(code, 0)
        self.assertIn("/tmp/baby.wav", output.getvalue())

    def test_first_recording_requires_explicit_audio_consent(self):
        from src import cli

        errors = io.StringIO()
        with (
            patch.object(cli.store, "list_episodes", return_value=[]),
            patch("builtins.input", return_value="no"),
            patch.object(
                cli.session,
                "record",
                side_effect=AssertionError("must not record without consent"),
            ),
            redirect_stderr(errors),
        ):
            code = cli.main(["record", "baby-01", "--seconds", "1.0"])

        self.assertEqual(code, 1)
        self.assertIn("consent", errors.getvalue().casefold())
        self.assertIn("audio", errors.getvalue().casefold())

    def test_finish_command_prints_prior_memory_without_similarity_number(self):
        from src import cli

        episode = {
            "id": 4,
            "subject_id": "baby-01",
            "fingerprint": [0.0] * 87,
            "outcome": "settled after feeding",
            "outcome_src": "caregiver",
        }
        match = {
            "episode_id": 1,
            "similarity": 0.9432,
            "band": "strong",
            "started_at": "2026-07-20T03:00:00-04:00",
            "interventions": [
                {
                    "order": 1,
                    "action": "offered bottle",
                    "evidence": "offered a bottle",
                }
            ],
            "outcome": "fed him",
            "outcome_src": "caregiver",
        }
        fake_retrieve = SimpleNamespace(
            find_similar=lambda *args, **kwargs: [match],
            episode_count=lambda subject_id: 4,
        )

        output = io.StringIO()
        with (
            patch.object(cli.session, "finish", return_value=episode),
            patch.object(cli, "retrieve", fake_retrieve, create=True),
            patch.object(
                cli.store,
                "list_episodes",
                return_value=[
                    {"duration_s": 60, "worked": False},
                    {"duration_s": 60, "worked": False},
                    {"duration_s": 60, "worked": False},
                ],
            ),
            redirect_stdout(output),
        ):
            try:
                code = cli.main(
                    [
                        "finish",
                        "baby-01",
                        "/tmp/baby.wav",
                        "--answer",
                        "settled after feeding",
                    ]
                )
            except SystemExit:
                self.fail("finish must be a supported CLI command")

        rendered = output.getvalue()
        self.assertEqual(code, 0)
        self.assertIn("strong", rendered.casefold())
        self.assertIn("offered bottle", rendered)
        self.assertIn("fed him", rendered)
        self.assertIn("step away", rendered.casefold())
        self.assertIn("pediatrician", rendered.casefold())
        self.assertNotIn("0.9432", rendered)

    def test_history_command_prints_outcome_source(self):
        from src import cli

        fake_store = SimpleNamespace(
            list_episodes=lambda subject_id: [
                {
                    "id": 3,
                    "started_at": "2026-07-29T03:00:00-04:00",
                    "outcome": "rocking settled her",
                    "outcome_src": "inferred",
                    "worked": True,
                }
            ]
        )
        output = io.StringIO()
        with (
            patch.object(cli, "store", fake_store, create=True),
            redirect_stdout(output),
        ):
            try:
                code = cli.main(["history", "baby-01"])
            except SystemExit:
                self.fail("history must be a supported CLI command")

        rendered = output.getvalue()
        self.assertEqual(code, 0)
        self.assertIn("rocking settled her", rendered)
        self.assertIn("inferred", rendered)

    def test_diary_command_prints_the_generated_diary(self):
        from src import cli

        fake_diary = SimpleNamespace(
            render_markdown=lambda subject_id: "# Cry diary - baby-01\n\nSynthetic warning"
        )
        output = io.StringIO()
        with (
            patch.object(cli, "diary", fake_diary, create=True),
            redirect_stdout(output),
        ):
            try:
                code = cli.main(["diary", "baby-01"])
            except SystemExit:
                self.fail("diary must be a supported CLI command")

        self.assertEqual(code, 0)
        self.assertIn("# Cry diary", output.getvalue())
        self.assertIn("Synthetic warning", output.getvalue())


if __name__ == "__main__":
    unittest.main()
