import importlib
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src import config, database


class RuntimeConfigTests(unittest.TestCase):
    def test_environment_paths_share_one_data_root(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "persistent"
            environment = {
                "IM_DATA_ROOT": str(root),
                "IM_DB_PATH": str(root / "custom.sqlite"),
                "IM_AUDIO_DIR": str(root / "captures"),
                "IM_MODEL_DIR": str(root / "weights"),
                "IM_VISITOR_ROOT": str(root / "guests"),
                "IM_OPENAI_ENV_PATH": str(root / "optional.env"),
            }
            with mock.patch.dict(os.environ, environment, clear=False):
                reloaded = importlib.reload(config)
                self.assertEqual(str(root), reloaded.DATA_ROOT)
                self.assertEqual(str(root / "custom.sqlite"), reloaded.DB_PATH)
                self.assertEqual(str(root / "captures"), reloaded.AUDIO_DIR)
                self.assertEqual(str(root / "weights"), reloaded.MODEL_DIR)
                self.assertEqual(str(root / "guests"), reloaded.VISITOR_ROOT)
                self.assertEqual(
                    str(root / "optional.env"),
                    reloaded.OPENAI_ENV_PATH,
                )
        importlib.reload(config)

    def test_default_secret_file_is_empty_instead_of_personal_path(self):
        with mock.patch.dict(
            os.environ,
            {"IM_OPENAI_ENV_PATH": ""},
            clear=False,
        ):
            reloaded = importlib.reload(config)
            self.assertEqual("", reloaded.OPENAI_ENV_PATH)
        importlib.reload(config)


class DatabaseConnectionTests(unittest.TestCase):
    def test_connection_enables_foreign_keys_and_busy_timeout(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = str(Path(temporary) / "runtime.sqlite")
            connection = database.connect(path)
            try:
                foreign_keys = connection.execute(
                    "PRAGMA foreign_keys"
                ).fetchone()[0]
                busy_timeout = connection.execute(
                    "PRAGMA busy_timeout"
                ).fetchone()[0]
                journal_mode = connection.execute(
                    "PRAGMA journal_mode"
                ).fetchone()[0]
                self.assertEqual(1, foreign_keys)
                self.assertGreaterEqual(busy_timeout, 5000)
                self.assertEqual("wal", str(journal_mode).casefold())
                self.assertIs(connection.row_factory, sqlite3.Row)
            finally:
                connection.close()


if __name__ == "__main__":
    unittest.main()
