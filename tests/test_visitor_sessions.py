import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src import store, visitor_sessions


class Clock:
    def __init__(self):
        self.value = datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc)

    def now(self):
        return self.value


class VisitorSessionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.template_db = self.root / "demo.sqlite"
        self.registry_db = self.root / "registry.sqlite"
        self.visitor_root = self.root / "visitors"
        self.audio_root = self.root / "audio"
        store.init_db(str(self.template_db))
        connection = sqlite3.connect(self.template_db)
        try:
            connection.execute(
                "INSERT INTO profile(display_name,kind,status,created_at) "
                "VALUES(?,?,?,?)",
                ("Demo Baby", "infant", "ready", "2026-07-30T10:00:00+00:00"),
            )
            connection.commit()
        finally:
            connection.close()
        self.clock = Clock()
        self.manager = visitor_sessions.VisitorSessionManager(
            template_db=self.template_db,
            registry_db=self.registry_db,
            visitor_root=self.visitor_root,
            audio_root=self.audio_root,
            ttl_seconds=3600,
            now=self.clock.now,
        )

    def tearDown(self):
        self.temporary.cleanup()

    def test_create_clones_demo_database_without_storing_raw_token(self):
        session = self.manager.resolve()
        self.assertTrue(session.is_new)
        self.assertTrue(session.database_path.is_file())
        self.assertTrue(session.audio_root.is_dir())

        connection = sqlite3.connect(session.database_path)
        try:
            row = connection.execute(
                "SELECT display_name FROM profile"
            ).fetchone()
            self.assertEqual("Demo Baby", row[0])
        finally:
            connection.close()

        registry = sqlite3.connect(self.registry_db)
        try:
            stored = registry.execute(
                "SELECT token_hash FROM visitor_session"
            ).fetchone()[0]
            self.assertEqual(session.token_hash, stored)
            columns = {
                row[1]
                for row in registry.execute(
                    "PRAGMA table_info(visitor_session)"
                ).fetchall()
            }
            self.assertNotIn("token", columns)
        finally:
            registry.close()

    def test_resolve_reuses_valid_token_and_consent_is_persisted(self):
        created = self.manager.resolve()
        loaded = self.manager.resolve(created.token)
        self.assertFalse(loaded.is_new)
        self.assertEqual(created.token_hash, loaded.token_hash)
        self.assertFalse(loaded.consented)

        consented = self.manager.consent(created.token)
        self.assertIsNotNone(consented)
        self.assertTrue(consented.consented)
        self.assertTrue(self.manager.resolve(created.token).consented)

    def test_expiry_creates_a_new_session_and_deletes_old_files(self):
        first = self.manager.resolve()
        marker = first.audio_root / "captured.wav"
        marker.write_bytes(b"audio")
        self.clock.value += timedelta(hours=1, seconds=1)

        replacement = self.manager.resolve(first.token)
        self.assertNotEqual(first.token_hash, replacement.token_hash)
        self.assertFalse(first.database_path.exists())
        self.assertFalse(first.audio_root.exists())

    def test_delete_removes_only_the_target_session(self):
        first = self.manager.resolve()
        second = self.manager.resolve()
        (first.audio_root / "one.wav").write_bytes(b"one")
        (second.audio_root / "two.wav").write_bytes(b"two")

        self.assertTrue(self.manager.delete(first.token))
        self.assertFalse(first.database_path.exists())
        self.assertFalse(first.audio_root.exists())
        self.assertTrue(second.database_path.exists())
        self.assertTrue(second.audio_root.exists())
        self.assertFalse(self.manager.delete(first.token))

    def test_cleanup_expired_preserves_active_sessions(self):
        expired = self.manager.resolve()
        self.clock.value += timedelta(minutes=30)
        active = self.manager.resolve()
        self.clock.value += timedelta(minutes=31)

        self.assertEqual(1, self.manager.cleanup_expired())
        self.assertFalse(expired.database_path.exists())
        self.assertTrue(active.database_path.exists())


if __name__ == "__main__":
    unittest.main()
