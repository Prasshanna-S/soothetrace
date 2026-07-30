import importlib
import io
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch


class HostedBootstrapTests(unittest.TestCase):
    def test_bootstrap_prepares_persistent_storage_and_warms_release_models(self):
        """Removing the hosted bootstrap setup must fail this storage-ready contract."""
        try:
            bootstrap = importlib.import_module("scripts.hosted_bootstrap")
        except ModuleNotFoundError:
            self.fail("scripts.hosted_bootstrap must provide the hosted bootstrap command")

        with TemporaryDirectory() as temporary:
            data_root = Path(temporary) / "persistent"
            database = data_root / "episodes.db"
            prepared = []

            with (
                patch.object(bootstrap.store, "init_db") as initialize,
                patch.object(
                    bootstrap.store,
                    "get_baseline",
                    return_value={"n": 421, "mu": [0.0], "sd": [1.0]},
                ),
                patch.object(bootstrap.encoders, "warm", return_value={
                    "mfcc87-v1": True,
                    "ecapa-cryceleb-v1": True,
                }) as warm_encoders,
                patch.object(bootstrap.cry_gate, "warm", return_value=True) as warm_cry_gate,
                patch.object(
                    bootstrap,
                    "_prepare_demo",
                    side_effect=lambda db_path, audio_root: prepared.append(
                        (db_path, audio_root)
                    ),
                ),
            ):
                code = bootstrap.main(
                    ["--data-root", str(data_root), "--db", str(database)]
                )

            self.assertEqual(0, code)
            self.assertTrue((data_root / "audio").is_dir())
            self.assertTrue((data_root / "models").is_dir())
            initialize.assert_called_once_with(str(database.resolve()))
            self.assertEqual(
                [(str(database.resolve()), str((data_root / "audio").resolve()))],
                prepared,
            )
            warm_encoders.assert_called_once()
            warm_cry_gate.assert_called_once_with()

    def test_bootstrap_fails_before_demo_or_model_warm_without_population_baseline(self):
        """Launching without calibrated baseline must not produce a partially ready release."""
        try:
            bootstrap = importlib.import_module("scripts.hosted_bootstrap")
        except ModuleNotFoundError:
            self.fail("scripts.hosted_bootstrap must provide the hosted bootstrap command")

        with TemporaryDirectory() as temporary:
            data_root = Path(temporary) / "persistent"
            database = data_root / "episodes.db"
            errors = io.StringIO()
            with (
                patch.object(bootstrap.store, "init_db"),
                patch.object(bootstrap.store, "get_baseline", return_value=None),
                patch.object(bootstrap, "_prepare_demo") as prepare_demo,
                patch.object(bootstrap.encoders, "warm") as warm_encoders,
                patch.object(bootstrap.cry_gate, "warm") as warm_cry_gate,
                redirect_stderr(errors),
            ):
                code = bootstrap.main(
                    ["--data-root", str(data_root), "--db", str(database)]
                )

            self.assertEqual(1, code)
            self.assertIn("population baseline", errors.getvalue().casefold())
            prepare_demo.assert_not_called()
            warm_encoders.assert_not_called()
            warm_cry_gate.assert_not_called()

    def test_bootstrap_rejects_a_missing_required_encoder_result(self):
        """A warm result that omits an encoder must not pass release readiness."""
        bootstrap = importlib.import_module("scripts.hosted_bootstrap")

        with TemporaryDirectory() as temporary:
            data_root = Path(temporary) / "persistent"
            database = data_root / "episodes.db"
            errors = io.StringIO()
            with (
                patch.object(bootstrap.store, "init_db"),
                patch.object(
                    bootstrap.store,
                    "get_baseline",
                    return_value={"n": 421, "mu": [0.0], "sd": [1.0]},
                ),
                patch.object(bootstrap, "_prepare_demo"),
                patch.object(
                    bootstrap.encoders,
                    "warm",
                    return_value={"mfcc87-v1": True},
                ),
                patch.object(bootstrap.cry_gate, "warm") as warm_cry_gate,
                redirect_stderr(errors),
            ):
                code = bootstrap.main(
                    ["--data-root", str(data_root), "--db", str(database)]
                )

            self.assertEqual(1, code)
            self.assertIn("required encoders", errors.getvalue().casefold())
            warm_cry_gate.assert_not_called()


class HostedDeploymentAssetsTests(unittest.TestCase):
    def _read_release_file(self, name: str) -> str:
        path = Path(__file__).resolve().parents[1] / name
        if not path.is_file():
            self.fail(f"{name} must be included in the hosted release package")
        return path.read_text(encoding="utf-8")

    def test_docker_runtime_uses_persistent_paths_and_non_root_proxy_server(self):
        """A release image must not write audio or SQLite into its ephemeral root filesystem."""
        dockerfile = self._read_release_file("Dockerfile")

        self.assertIn("python:3.12-slim", dockerfile)
        self.assertIn("ffmpeg", dockerfile)
        self.assertIn("USER soothetrace", dockerfile)
        self.assertIn("IM_DATA_ROOT=/var/data", dockerfile)
        self.assertIn("IM_DB_PATH=/var/data/episodes.db", dockerfile)
        self.assertIn("IM_AUDIO_DIR=/var/data/audio", dockerfile)
        self.assertIn("IM_MODEL_DIR=/var/data/models", dockerfile)
        self.assertIn("--behind-tls-proxy", dockerfile)
        self.assertIn("${PORT:-10000}", dockerfile)

    def test_render_blueprint_uses_one_persistent_instance_with_readiness_check(self):
        """A second instance or an ephemeral disk would split persistent SQLite state."""
        blueprint = self._read_release_file("render.yaml")

        self.assertIn("runtime: docker", blueprint)
        self.assertIn("healthCheckPath: /readyz", blueprint)
        self.assertIn("numInstances: 1", blueprint)
        self.assertIn("mountPath: /var/data", blueprint)
        self.assertIn("IM_DATA_ROOT", blueprint)
        self.assertIn("OPENAI_API_KEY", blueprint)

    def test_release_files_exclude_local_state_and_document_required_environment(self):
        """Build context must not leak local artifacts and operators need the hosted paths."""
        dockerignore = self._read_release_file(".dockerignore")
        environment = self._read_release_file(".env.example")

        self.assertIn(".venv/", dockerignore)
        self.assertIn("node_modules/", dockerignore)
        self.assertIn("models/", dockerignore)
        self.assertIn("data/audio/", dockerignore)
        self.assertIn("*.db", dockerignore)
        self.assertIn("IM_DATA_ROOT=/var/data", environment)
        self.assertIn("IM_DB_PATH=/var/data/episodes.db", environment)
        self.assertIn("IM_AUDIO_DIR=/var/data/audio", environment)
        self.assertIn("IM_MODEL_DIR=/var/data/models", environment)
        self.assertIn("OPENAI_API_KEY=", environment)


if __name__ == "__main__":
    unittest.main()
