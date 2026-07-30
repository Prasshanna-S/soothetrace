"""Persistent infant care-session state and privacy boundaries."""
from __future__ import annotations

import json
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from src import care_sessions, identity, store


class CareSessionTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.root = Path(self.tempdir.name)
        self.db = str(self.root / "care.db")
        store.init_db(self.db)

    def _profile(self, name="Baby A", kind=identity.KIND_INFANT):
        return identity.create_profile(name, kind, self.db)

    def _set_profile_status(self, profile_id, status):
        with sqlite3.connect(self.db) as connection:
            connection.execute(
                "UPDATE profile SET status=? WHERE id=?",
                (status, profile_id),
            )

    def _set_session_state(self, session_id, status, **fields):
        assignments = ["status=?"]
        values = [status]
        for key, value in fields.items():
            assignments.append(f"{key}=?")
            values.append(value)
        values.append(session_id)
        with sqlite3.connect(self.db) as connection:
            connection.execute(
                f"UPDATE care_session SET {','.join(assignments)} WHERE id=?",
                values,
            )

    def _insert_chunk(self, session_id, paths):
        with sqlite3.connect(self.db) as connection:
            connection.execute(
                "INSERT INTO care_session_chunk ("
                "session_id, sequence, created_at, source_audio_path, "
                "canonical_audio_path, identity_audio_path, audio_sha256, "
                "capture_metadata_json, quality_json, status, cry_status, "
                "cry_reason_codes, cry_model_version, matched_profile_id, "
                "reason_codes, result_json"
                ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    session_id,
                    1,
                    "2026-07-30T12:00:00+00:00",
                    paths[0],
                    paths[1],
                    paths[2],
                    "secret-digest",
                    "{}",
                    "{}",
                    "invalid",
                    "invalid_audio",
                    "[]",
                    None,
                    None,
                    "[]",
                    "{}",
                ),
            )

    def assert_error(self, result, reason):
        self.assertEqual({"status": "error", "reason": reason}, result)

    def test_schema_migration_adds_all_care_tables_columns_and_indexes(self):
        with sqlite3.connect(self.db) as connection:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            columns = {
                table: {
                    row[1]
                    for row in connection.execute(f"PRAGMA table_info({table})")
                }
                for table in ("care_session", "care_session_chunk", "care_event")
            }
            indexes = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='index'"
                )
            }

        self.assertTrue(
            {"episode", "profile", "care_session", "care_session_chunk", "care_event"}
            <= tables
        )
        self.assertEqual(
            {
                "id",
                "profile_id",
                "status",
                "created_at",
                "paused_at",
                "stopped_at",
                "completed_at",
                "last_sequence",
                "latest_matched_chunk_id",
                "selected_chunk_id",
                "decision_json",
                "episode_id",
                "tags_json",
            },
            columns["care_session"],
        )
        self.assertEqual(
            {
                "id",
                "session_id",
                "sequence",
                "created_at",
                "source_audio_path",
                "canonical_audio_path",
                "identity_audio_path",
                "audio_sha256",
                "capture_metadata_json",
                "quality_json",
                "status",
                "cry_status",
                "cry_reason_codes",
                "cry_model_version",
                "matched_profile_id",
                "reason_codes",
                "result_json",
            },
            columns["care_session_chunk"],
        )
        self.assertEqual(
            {"id", "profile_id", "event_type", "occurred_at", "details", "created_at"},
            columns["care_event"],
        )
        self.assertTrue(
            {
                "idx_care_session_status",
                "idx_care_session_chunk_order",
                "idx_care_event_profile_time",
                "idx_episode_profile_history",
            }
            <= indexes
        )

    def test_chunk_sequence_is_unique_within_each_session(self):
        profile = self._profile()
        session = care_sessions.create(profile["id"], db_path=self.db)
        paths = [str(self.root / name) for name in ("source", "canonical", "identity")]
        self._insert_chunk(session["id"], paths)

        with self.assertRaises(sqlite3.IntegrityError):
            self._insert_chunk(session["id"], paths)

    def test_create_accepts_only_active_infant_profiles(self):
        active = self._profile("Active infant")
        archived = self._profile("Archived infant")
        imitation = self._profile("Adult", identity.KIND_IMITATION)
        self._set_profile_status(archived["id"], "archived")

        self.assertEqual(
            "listening",
            care_sessions.create(active["id"], db_path=self.db)["status"],
        )
        for profile_id in (archived["id"], imitation["id"], 999999):
            with self.subTest(profile_id=profile_id):
                self.assert_error(
                    care_sessions.create(profile_id, db_path=self.db),
                    "invalid_care_session_profile",
                )

    def test_create_normalizes_deduplicates_and_caps_tags(self):
        profile = self._profile()
        tags = (
            [" Tag 0 ", "tag 0", "Straße", "STRASSE"]
            + [f" Tag {index} " for index in range(1, 26)]
            + ["   "]
        )

        session = care_sessions.create(profile["id"], tags, self.db)

        self.assertEqual(
            ["tag 0", "strasse"] + [f"tag {index}" for index in range(1, 19)],
            session["tags"],
        )

    def test_create_starts_listening_with_empty_decision(self):
        profile = self._profile()

        session = care_sessions.create(profile["id"], [" Evening "], self.db)

        self.assertEqual("listening", session["status"])
        self.assertEqual(0, session["last_sequence"])
        self.assertEqual(["evening"], session["tags"])
        self.assertIsNone(session["decision"])
        self.assertIsNone(session["paused_at"])
        self.assertIsNone(session["stopped_at"])
        self.assertIsNone(session["completed_at"])
        self.assertIsNotNone(session["started_at"])
        self.assertEqual(
            {"id", "display_name", "kind", "status", "enrollments"},
            set(session["profile"]),
        )

    def test_pause_and_resume_follow_the_state_table(self):
        profile = self._profile()
        session = care_sessions.create(profile["id"], db_path=self.db)

        paused = care_sessions.pause(session["id"], self.db)
        resumed = care_sessions.resume(session["id"], self.db)

        self.assertEqual("paused", paused["status"])
        self.assertIsNotNone(paused["paused_at"])
        self.assertEqual("listening", resumed["status"])
        self.assertEqual(paused["paused_at"], resumed["paused_at"])

    def test_stop_from_listening_or_paused_enters_awaiting_outcome(self):
        profile = self._profile()
        listening = care_sessions.create(profile["id"], db_path=self.db)
        paused = care_sessions.create(profile["id"], db_path=self.db)
        care_sessions.pause(paused["id"], self.db)

        stopped_listening = care_sessions.stop(listening["id"], self.db)
        stopped_paused = care_sessions.stop(paused["id"], self.db)

        for stopped in (stopped_listening, stopped_paused):
            self.assertEqual("awaiting_outcome", stopped["status"])
            self.assertIsNotNone(stopped["stopped_at"])

    def test_stop_is_idempotent_after_awaiting_outcome(self):
        profile = self._profile()
        session = care_sessions.create(profile["id"], db_path=self.db)
        first = care_sessions.stop(session["id"], self.db)

        second = care_sessions.stop(session["id"], self.db)

        self.assertEqual(first, second)

    def test_concurrent_stop_cas_loser_returns_winning_snapshot(self):
        profile = self._profile()
        session = care_sessions.create(profile["id"], db_path=self.db)
        rendezvous = threading.Barrier(2)
        real_session_row = care_sessions._session_row
        results = []
        thread_errors = []

        def synchronized_session_row(connection, session_id):
            row = real_session_row(connection, session_id)
            if row and row["status"] == "listening":
                rendezvous.wait(timeout=3)
            return row

        def run_stop():
            try:
                results.append(care_sessions.stop(session["id"], self.db))
            except BaseException as exc:
                thread_errors.append(exc)

        threads = [threading.Thread(target=run_stop) for _ in range(2)]
        with patch.object(
            care_sessions,
            "_session_row",
            side_effect=synchronized_session_row,
        ):
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=5)

        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual([], thread_errors)
        self.assertEqual(2, len(results))
        self.assertEqual(results[0], results[1])
        self.assertEqual("awaiting_outcome", results[0]["status"])
        self.assertIsNotNone(results[0]["stopped_at"])

    def test_invalid_transitions_do_not_change_state(self):
        profile = self._profile()
        session = care_sessions.create(profile["id"], db_path=self.db)

        self.assert_error(
            care_sessions.resume(session["id"], self.db),
            "invalid_care_session_transition",
        )
        self.assertEqual(
            "listening",
            care_sessions.get(session["id"], self.db)["status"],
        )

        care_sessions.pause(session["id"], self.db)
        self.assert_error(
            care_sessions.pause(session["id"], self.db),
            "invalid_care_session_transition",
        )
        self.assertEqual(
            "paused",
            care_sessions.get(session["id"], self.db)["status"],
        )

    def test_complete_and_discarded_sessions_are_immutable(self):
        profile = self._profile()
        complete = care_sessions.create(profile["id"], db_path=self.db)
        discarded = care_sessions.create(profile["id"], db_path=self.db)
        self._set_session_state(
            complete["id"],
            "complete",
            completed_at="2026-07-30T12:00:00+00:00",
        )
        self._set_session_state(discarded["id"], "discarded")

        for session in (complete, discarded):
            for operation in (
                care_sessions.pause,
                care_sessions.resume,
                care_sessions.stop,
            ):
                with self.subTest(session=session["id"], operation=operation.__name__):
                    self.assert_error(
                        operation(session["id"], self.db),
                        "invalid_care_session_transition",
                    )

    def test_public_snapshot_uses_recursive_decision_schema_allowlist(self):
        profile = self._profile()
        session = care_sessions.create(profile["id"], db_path=self.db)
        decision = {
            "id": 8,
            "latched_at": "2026-07-30T20:15:15-04:00",
            "profile": {
                "id": profile["id"],
                "display_name": "Baby A",
                "artifact": "/private/profile.bin",
                "candidate_profiles": [{"id": 99}],
            },
            "guidance": {
                "status": "grounded",
                "headline": "What helped before",
                "interpretation": "This resembles earlier incidents.",
                "recommendation": "Held baby upright.",
                "evidence_summary": "Supported by 2 incidents.",
                "support_count": 2,
                "incident_ids": [101, 97, {"hash": "secret"}],
                "pattern": "similar time of day",
                "cosine": 0.99,
                "candidate_profiles": [99],
                "_rank": 1,
            },
            "basis": [
                "cry pattern was the strongest available signal",
                {"artifact": "/private/basis.bin"},
            ],
            "scenarios": [
                {
                    "episode_id": 101,
                    "started_at": "2026-07-27T20:04:00-04:00",
                    "interventions": [
                        {
                            "order": 1,
                            "action": "held baby upright",
                            "evidence": "held the baby upright",
                            "hash": "secret",
                        },
                        {"action": {"path": "/private/action.txt"}},
                    ],
                    "outcome": "The baby settled.",
                    "outcome_src": "caregiver",
                    "worked": True,
                    "contributions": [
                        "occurred at a similar time of day",
                        {"cosine": 0.88},
                    ],
                    "audio_url": "/api/audio/episodes/101",
                    "artifact": "/private/episode.wav",
                    "audio_path": "/private/episode.wav",
                    "embedding": [1.0],
                    "candidate_profiles": [99],
                    "_debug_score": 4.2,
                },
                {"episode_id": "not-an-integer", "hash": "secret"},
            ],
            "artifact": "/private/session.json",
            "cosine": 0.97,
            "candidate_profiles": [99],
            "sha512": "secret",
            "_debug": {"path": "/private/debug"},
        }
        with sqlite3.connect(self.db) as connection:
            connection.execute(
                "UPDATE care_session SET decision_json=? WHERE id=?",
                (json.dumps(decision), session["id"]),
            )

        snapshot = care_sessions.get(session["id"], self.db)

        self.assertEqual(
            {
                "id": 8,
                "latched_at": "2026-07-30T20:15:15-04:00",
                "profile": {
                    "id": profile["id"],
                    "display_name": "Baby A",
                },
                "guidance": {
                    "status": "grounded",
                    "headline": "What helped before",
                    "interpretation": "This resembles earlier incidents.",
                    "recommendation": "Held baby upright.",
                    "evidence_summary": "Supported by 2 incidents.",
                    "support_count": 2,
                    "incident_ids": [101, 97],
                    "pattern": "similar time of day",
                },
                "basis": ["cry pattern was the strongest available signal"],
                "scenarios": [
                    {
                        "episode_id": 101,
                        "started_at": "2026-07-27T20:04:00-04:00",
                        "interventions": [
                            {
                                "order": 1,
                                "action": "held baby upright",
                                "evidence": "held the baby upright",
                            }
                        ],
                        "outcome": "The baby settled.",
                        "outcome_src": "caregiver",
                        "worked": True,
                        "contributions": ["occurred at a similar time of day"],
                        "audio_url": "/api/audio/episodes/101",
                    }
                ],
            },
            snapshot["decision"],
        )
        self.assertEqual(
            {
                "id",
                "status",
                "profile",
                "started_at",
                "paused_at",
                "stopped_at",
                "completed_at",
                "last_sequence",
                "tags",
                "decision",
            },
            set(snapshot),
        )

    def test_discard_deletes_only_files_beneath_managed_root(self):
        profile = self._profile()
        session = care_sessions.create(profile["id"], db_path=self.db)
        managed_root = self.root / "managed"
        managed_root.mkdir()
        managed = managed_root / "session.wav"
        sibling = self.root / "managed-other" / "sibling.wav"
        outside = self.root / "outside.wav"
        sibling.parent.mkdir()
        for path in (managed, sibling, outside):
            path.write_bytes(b"audio")
        self._insert_chunk(
            session["id"],
            [str(managed), str(sibling), str(outside)],
        )

        result = care_sessions.discard(session["id"], managed_root, self.db)

        self.assertEqual("discarded", result["status"])
        self.assertFalse(managed.exists())
        self.assertTrue(sibling.exists())
        self.assertTrue(outside.exists())

    def test_discard_claims_state_before_cleanup_can_race_completion(self):
        profile = self._profile()
        session = care_sessions.create(profile["id"], db_path=self.db)
        care_sessions.stop(session["id"], self.db)
        managed_root = self.root / "managed"
        managed_root.mkdir()
        audio = managed_root / "selected.wav"
        audio.write_bytes(b"audio")
        self._insert_chunk(
            session["id"],
            [str(audio), str(audio), str(audio)],
        )
        unlink_entered = threading.Event()
        completion_attempted = threading.Event()
        discard_finished = threading.Event()
        completion_rowcounts = []
        discard_results = []
        thread_errors = []
        original_unlink = Path.unlink

        def synchronized_unlink(path, *args, **kwargs):
            unlink_entered.set()
            if not completion_attempted.wait(timeout=3):
                raise AssertionError("completion did not attempt its write")
            return original_unlink(path, *args, **kwargs)

        def complete_during_cleanup():
            connection = None
            try:
                if not unlink_entered.wait(timeout=3):
                    raise AssertionError("discard did not reach cleanup")
                connection = sqlite3.connect(self.db, timeout=0)
                try:
                    cursor = connection.execute(
                        "UPDATE care_session SET status='complete', episode_id=99, "
                        "completed_at='2026-07-30T12:00:00+00:00' "
                        "WHERE id=? AND status='awaiting_outcome'",
                        (session["id"],),
                    )
                    connection.commit()
                    completion_rowcounts.append(cursor.rowcount)
                    completion_attempted.set()
                except sqlite3.OperationalError as exc:
                    if "locked" not in str(exc).casefold():
                        raise
                    connection.rollback()
                    completion_attempted.set()
                    if not discard_finished.wait(timeout=3):
                        raise AssertionError("discard did not release its write claim")
                    cursor = connection.execute(
                        "UPDATE care_session SET status='complete', episode_id=99, "
                        "completed_at='2026-07-30T12:00:00+00:00' "
                        "WHERE id=? AND status='awaiting_outcome'",
                        (session["id"],),
                    )
                    connection.commit()
                    completion_rowcounts.append(cursor.rowcount)
            except BaseException as exc:
                thread_errors.append(exc)
                completion_attempted.set()
            finally:
                if connection is not None:
                    connection.close()

        def run_discard():
            try:
                discard_results.append(
                    care_sessions.discard(session["id"], managed_root, self.db)
                )
            except BaseException as exc:
                thread_errors.append(exc)
            finally:
                discard_finished.set()

        completion_thread = threading.Thread(target=complete_during_cleanup)
        discard_thread = threading.Thread(target=run_discard)
        with patch.object(Path, "unlink", new=synchronized_unlink):
            completion_thread.start()
            discard_thread.start()
            discard_thread.join(timeout=5)
            completion_thread.join(timeout=5)

        self.assertFalse(discard_thread.is_alive())
        self.assertFalse(completion_thread.is_alive())
        self.assertEqual([], thread_errors)
        self.assertEqual([0], completion_rowcounts)
        self.assertEqual("discarded", discard_results[0]["status"])
        self.assertEqual(
            "discarded",
            care_sessions.get(session["id"], self.db)["status"],
        )
        self.assertFalse(audio.exists())

    def test_discard_unlink_failure_preserves_recoverable_session_and_file(self):
        profile = self._profile()
        session = care_sessions.create(profile["id"], db_path=self.db)
        managed_root = self.root / "managed"
        managed_root.mkdir()
        audio = managed_root / "locked.wav"
        audio.write_bytes(b"audio")
        self._insert_chunk(
            session["id"],
            [str(audio), str(audio), str(audio)],
        )

        with patch.object(
            Path,
            "unlink",
            side_effect=PermissionError("file is in use"),
        ):
            result = care_sessions.discard(session["id"], managed_root, self.db)

        self.assert_error(result, "care_session_cleanup_failed")
        self.assertEqual(
            "listening",
            care_sessions.get(session["id"], self.db)["status"],
        )
        self.assertTrue(audio.exists())

    def test_partial_cleanup_seals_session_and_retry_removes_remaining_file(self):
        profile = self._profile()
        session = care_sessions.create(profile["id"], db_path=self.db)
        managed_root = self.root / "managed"
        managed_root.mkdir()
        first = managed_root / "first.wav"
        second = managed_root / "second.wav"
        first.write_bytes(b"first")
        second.write_bytes(b"second")
        self._insert_chunk(
            session["id"],
            [str(first), str(second), str(second)],
        )
        real_unlink = Path.unlink
        second_resolved = second.resolve()

        def fail_second_unlink(path, *args, **kwargs):
            if path == second_resolved:
                raise PermissionError("second file is in use")
            return real_unlink(path, *args, **kwargs)

        with patch.object(Path, "unlink", new=fail_second_unlink):
            result = care_sessions.discard(session["id"], managed_root, self.db)

        self.assert_error(result, "care_session_cleanup_failed")
        self.assertFalse(first.exists())
        self.assertTrue(second.exists())
        self.assertEqual(
            "discarded",
            care_sessions.get(session["id"], self.db)["status"],
        )

        retry = care_sessions.discard(session["id"], managed_root, self.db)

        self.assertEqual("discarded", retry["status"])
        self.assertFalse(second.exists())

    def test_discard_refuses_completed_session_and_preserves_incident_audio(self):
        profile = self._profile()
        session = care_sessions.create(profile["id"], db_path=self.db)
        managed_root = self.root / "managed"
        managed_root.mkdir()
        incident_audio = managed_root / "episode.wav"
        incident_audio.write_bytes(b"saved")
        self._insert_chunk(
            session["id"],
            [str(incident_audio), str(incident_audio), str(incident_audio)],
        )
        self._set_session_state(
            session["id"],
            "complete",
            completed_at="2026-07-30T12:00:00+00:00",
            episode_id=17,
        )

        result = care_sessions.discard(session["id"], managed_root, self.db)

        self.assert_error(result, "invalid_care_session_transition")
        self.assertTrue(incident_audio.exists())
        self.assertEqual(
            "complete",
            care_sessions.get(session["id"], self.db)["status"],
        )

    def test_missing_session_returns_stable_domain_error(self):
        for operation in (
            care_sessions.get,
            care_sessions.pause,
            care_sessions.resume,
            care_sessions.stop,
        ):
            with self.subTest(operation=operation.__name__):
                self.assert_error(
                    operation(999999, self.db),
                    "no_such_care_session",
                )
        self.assert_error(
            care_sessions.discard(999999, self.root, self.db),
            "no_such_care_session",
        )


if __name__ == "__main__":
    unittest.main()
