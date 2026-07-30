"""Persistent infant care-session state and privacy boundaries."""
from __future__ import annotations

import hashlib
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

    def _insert_matched_chunk(
        self,
        session_id,
        profile_id,
        sequence,
        created_at,
        name,
    ):
        ingested = self._ingested(name, payload=f"audio-{sequence}".encode())
        with sqlite3.connect(self.db) as connection:
            cursor = connection.execute(
                "INSERT INTO care_session_chunk ("
                "session_id, sequence, created_at, source_audio_path, "
                "canonical_audio_path, identity_audio_path, audio_sha256, "
                "capture_metadata_json, quality_json, status, cry_status, "
                "cry_reason_codes, cry_model_version, matched_profile_id, "
                "reason_codes, result_json"
                ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    session_id,
                    sequence,
                    created_at,
                    ingested["source_path"],
                    ingested["canonical_path"],
                    ingested["identity_path"],
                    hashlib.sha256(f"audio-{sequence}".encode()).hexdigest(),
                    "{}",
                    "{}",
                    "matched_no_guidance",
                    "infant_cry_detected",
                    '["infant_cry_evidence_strong"]',
                    "ast-audioset-baby-cry-v1",
                    profile_id,
                    '["insufficient_history"]',
                    "{}",
                ),
            )
            chunk_id = int(cursor.lastrowid)
            connection.execute(
                "UPDATE care_session SET last_sequence=?, "
                "latest_matched_chunk_id=? WHERE id=?",
                (sequence, chunk_id, session_id),
            )
        return {
            "id": chunk_id,
            "created_at": created_at,
            "canonical_path": ingested["canonical_path"],
        }

    def _ingested(self, name, payload=b"source-audio"):
        capture_dir = self.root / "managed" / name
        capture_dir.mkdir(parents=True, exist_ok=True)
        source = capture_dir / "source.webm"
        canonical = capture_dir / "canonical.wav"
        identity_audio = capture_dir / "identity.wav"
        source.write_bytes(payload)
        canonical.write_bytes(b"canonical-" + payload)
        identity_audio.write_bytes(b"identity-" + payload)
        return {
            "status": "ready",
            "source_path": str(source),
            "canonical_path": str(canonical),
            "identity_path": str(identity_audio),
            "sha256": "caller-supplied-digest-must-not-be-trusted",
            "quality": {
                "duration_s": 12.0,
                "mean_db": -31.5,
                "peak_db": -8.0,
                "voiced_fraction": 0.42,
            },
            "capture": {
                "source": "microphone",
                "device": "iPhone Safari",
            },
            "versions": {
                "decode": "ffmpeg-pcm16-v1",
                "normalization": "rms-24db-v1",
            },
        }

    def _cry_result(self, status):
        reasons = {
            "infant_cry_detected": "infant_cry_evidence_strong",
            "cry_uncertain": "infant_cry_evidence_borderline",
            "no_cry_detected": "infant_cry_evidence_low",
            "gate_unavailable": "cry_gate_model_unavailable",
        }
        return {
            "status": status,
            "label": (
                "Infant-cry-like sound detected"
                if status == "infant_cry_detected"
                else None
            ),
            "reason_codes": [reasons[status]],
            "analyzed_duration_s": 10.0,
            "analysis_view_count": 1,
            "model_version": "ast-audioset-baby-cry-v1",
            "_infant_score": 0.91,
            "_generic_cry_score": 0.12,
        }

    def _selected_identity(self, profile_id):
        return {
            "status": "match",
            "profile_id": profile_id,
            "display_name": "Baby A",
            "kind": "infant",
            "score": 0.99,
            "margin": 0.31,
            "embedding": [0.1, 0.2],
            "candidates": [{"profile_id": profile_id, "score": 0.99}],
            "reasons": ["accepted"],
        }

    def _no_guidance_preview(self, profile):
        return {
            "status": "preview",
            "identity": {
                "profile_id": profile["id"],
                "display_name": profile["display_name"],
                "kind": "infant",
            },
            "scenarios": [],
            "guidance": {
                "status": "insufficient_history",
                "headline": "Not enough history yet",
                "recommendation": None,
                "incident_ids": [],
            },
            "_canonical_audio": "/private/internal.wav",
            "_current_context": {"hour_local": 3},
        }

    def _session_db_value(self, session_id, field):
        with sqlite3.connect(self.db) as connection:
            row = connection.execute(
                f"SELECT {field} FROM care_session WHERE id=?",
                (session_id,),
            ).fetchone()
        return row[0]

    def assert_public_result_has_no_sensitive_analysis(self, value):
        forbidden = (
            "score",
            "margin",
            "digest",
            "path",
            "embedding",
            "candidate",
        )

        def visit(item):
            if isinstance(item, dict):
                for key, child in item.items():
                    lowered = str(key).casefold()
                    self.assertFalse(
                        any(term in lowered for term in forbidden),
                        f"sensitive key was public: {key}",
                    )
                    self.assertFalse(lowered.startswith("_"))
                    visit(child)
            elif isinstance(item, list):
                for child in item:
                    visit(child)

        visit(value)

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
                        "audio_url": (
                            f"/api/profiles/{profile['id']}/incidents/101/audio"
                        ),
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

    def test_chunk_sequence_starts_at_one_and_rejects_gaps(self):
        profile = self._profile()
        session = care_sessions.create(profile["id"], db_path=self.db)
        with (
            patch.object(care_sessions, "cry_gate", create=True) as cry_gate,
            patch.object(care_sessions, "careflow", create=True) as careflow,
            patch.object(care_sessions.identity, "identify") as identify,
        ):
            first_gap = care_sessions.submit_chunk(
                session["id"],
                2,
                self._ingested("gap-first"),
                self.db,
            )
            cry_gate.classify.return_value = self._cry_result("no_cry_detected")
            accepted = care_sessions.submit_chunk(
                session["id"],
                1,
                self._ingested("accepted"),
                self.db,
            )
            later_gap = care_sessions.submit_chunk(
                session["id"],
                3,
                self._ingested("gap-later"),
                self.db,
            )

        self.assert_error(first_gap, "out_of_order_chunk")
        self.assertEqual("no_cry_detected", accepted["chunk"]["status"])
        self.assertEqual(1, accepted["chunk"]["sequence"])
        self.assertEqual(1, accepted["session"]["last_sequence"])
        self.assert_error(later_gap, "out_of_order_chunk")
        self.assertEqual(1, care_sessions.get(session["id"], self.db)["last_sequence"])
        identify.assert_not_called()
        careflow.preview_profile_incident.assert_not_called()

    def test_identical_replay_returns_original_result_after_later_state_changes(self):
        profile = self._profile()
        session = care_sessions.create(profile["id"], db_path=self.db)
        first_ingest = self._ingested("first-original", b"same-segment")
        replay_ingest = self._ingested("first-replay", b"same-segment")
        second_ingest = self._ingested("second", b"later-segment")
        grounded = {
            "status": "preview",
            "identity": {
                "profile_id": profile["id"],
                "display_name": "Baby A",
                "kind": "infant",
            },
            "scenarios": [
                {
                    "episode_id": 101,
                    "started_at": "2026-07-27T20:04:00-04:00",
                    "interventions": [
                        {
                            "order": 1,
                            "action": "held baby upright",
                            "evidence": "held baby upright",
                        }
                    ],
                    "outcome": "The baby settled.",
                    "outcome_src": "caregiver",
                    "worked": True,
                    "contributions": ["cry pattern was the strongest available signal"],
                    "audio_url": (
                        f"/api/profiles/{profile['id']}/incidents/101/audio"
                    ),
                }
            ],
            "guidance": {
                "status": "grounded",
                "headline": "What helped before",
                "interpretation": "This resembles earlier incidents.",
                "recommendation": "What helped before: held baby upright.",
                "evidence_summary": "Supported by 1 similar recorded incident.",
                "support_count": 1,
                "incident_ids": [101],
                "pattern": None,
            },
        }
        with (
            patch.object(care_sessions, "cry_gate", create=True) as cry_gate,
            patch.object(care_sessions.identity, "identify") as identify,
            patch.object(care_sessions, "careflow", create=True) as careflow,
        ):
            cry_gate.classify.side_effect = [
                self._cry_result("no_cry_detected"),
                self._cry_result("infant_cry_detected"),
            ]
            identify.return_value = self._selected_identity(profile["id"])
            careflow.preview_profile_incident.return_value = grounded
            original = care_sessions.submit_chunk(
                session["id"],
                1,
                first_ingest,
                self.db,
            )
            later = care_sessions.submit_chunk(
                session["id"],
                2,
                second_ingest,
                self.db,
            )
            replay = care_sessions.submit_chunk(
                session["id"],
                1,
                replay_ingest,
                self.db,
            )

        self.assertEqual("guidance_latched", later["chunk"]["status"])
        self.assertEqual(original, replay)
        self.assertEqual(1, replay["session"]["last_sequence"])
        self.assertIsNone(replay["session"]["decision"])
        self.assertEqual(2, cry_gate.classify.call_count)

    def test_repeated_sequence_with_different_bytes_is_a_conflict(self):
        profile = self._profile()
        session = care_sessions.create(profile["id"], db_path=self.db)
        with (
            patch.object(care_sessions, "cry_gate", create=True) as cry_gate,
            patch.object(care_sessions.identity, "identify") as identify,
        ):
            cry_gate.classify.return_value = self._cry_result("no_cry_detected")
            care_sessions.submit_chunk(
                session["id"],
                1,
                self._ingested("conflict-original", b"original"),
                self.db,
            )
            conflict = care_sessions.submit_chunk(
                session["id"],
                1,
                self._ingested("conflict-replacement", b"replacement"),
                self.db,
            )

        self.assert_error(conflict, "sequence_conflict")
        self.assertEqual(1, cry_gate.classify.call_count)
        identify.assert_not_called()

    def test_concurrent_identical_sequence_runs_inference_once_and_replays_winner(self):
        profile = self._profile()
        session = care_sessions.create(profile["id"], db_path=self.db)
        first = self._ingested("concurrent-identical-a", b"same-segment")
        second = self._ingested("concurrent-identical-b", b"same-segment")
        preflight = threading.Barrier(2)
        gate_started = threading.Event()
        release_gate = threading.Event()
        real_sequence_resolution = care_sessions._sequence_resolution
        preflight_calls = 0
        preflight_lock = threading.Lock()
        results = []
        errors = []

        def synchronize_preflight(connection, row, sequence, digest):
            nonlocal preflight_calls
            resolved = real_sequence_resolution(
                connection,
                row,
                sequence,
                digest,
            )
            with preflight_lock:
                preflight_calls += 1
                call_number = preflight_calls
            if (
                resolved is None
                and not connection.in_transaction
                and call_number <= 2
            ):
                preflight.wait(timeout=3)
            return resolved

        def classify(_audio_path):
            gate_started.set()
            if not release_gate.wait(timeout=3):
                raise TimeoutError("test did not release cry gate")
            return self._cry_result("infant_cry_detected")

        def submit(ingested):
            try:
                results.append(
                    care_sessions.submit_chunk(
                        session["id"],
                        1,
                        ingested,
                        self.db,
                    )
                )
            except BaseException as exc:
                errors.append(exc)

        with (
            patch.object(
                care_sessions,
                "_sequence_resolution",
                side_effect=synchronize_preflight,
            ),
            patch.object(care_sessions, "cry_gate", create=True) as cry_gate,
            patch.object(care_sessions.identity, "identify") as identify,
            patch.object(care_sessions, "careflow", create=True) as careflow,
        ):
            cry_gate.classify.side_effect = classify
            identify.return_value = self._selected_identity(profile["id"])
            careflow.preview_profile_incident.return_value = (
                self._no_guidance_preview(profile)
            )
            threads = [
                threading.Thread(target=submit, args=(ingested,))
                for ingested in (first, second)
            ]
            for thread in threads:
                thread.start()
            self.assertTrue(gate_started.wait(timeout=3))
            release_gate.set()
            for thread in threads:
                thread.join(timeout=5)

        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual([], errors)
        self.assertEqual(2, len(results))
        self.assertEqual(results[0], results[1])
        self.assertEqual(1, cry_gate.classify.call_count)
        self.assertEqual(1, identify.call_count)
        self.assertEqual(1, careflow.preview_profile_incident.call_count)

    def test_concurrent_conflicting_sequence_runs_inference_once_then_conflicts_loser(self):
        profile = self._profile()
        session = care_sessions.create(profile["id"], db_path=self.db)
        first = self._ingested("concurrent-conflict-a", b"segment-a")
        second = self._ingested("concurrent-conflict-b", b"segment-b")
        preflight = threading.Barrier(2)
        gate_started = threading.Event()
        release_gate = threading.Event()
        real_sequence_resolution = care_sessions._sequence_resolution
        preflight_calls = 0
        preflight_lock = threading.Lock()
        results = []
        errors = []

        def synchronize_preflight(connection, row, sequence, digest):
            nonlocal preflight_calls
            resolved = real_sequence_resolution(
                connection,
                row,
                sequence,
                digest,
            )
            with preflight_lock:
                preflight_calls += 1
                call_number = preflight_calls
            if (
                resolved is None
                and not connection.in_transaction
                and call_number <= 2
            ):
                preflight.wait(timeout=3)
            return resolved

        def classify(_audio_path):
            gate_started.set()
            if not release_gate.wait(timeout=3):
                raise TimeoutError("test did not release cry gate")
            return self._cry_result("infant_cry_detected")

        def submit(ingested):
            try:
                results.append(
                    care_sessions.submit_chunk(
                        session["id"],
                        1,
                        ingested,
                        self.db,
                    )
                )
            except BaseException as exc:
                errors.append(exc)

        with (
            patch.object(
                care_sessions,
                "_sequence_resolution",
                side_effect=synchronize_preflight,
            ),
            patch.object(care_sessions, "cry_gate", create=True) as cry_gate,
            patch.object(care_sessions.identity, "identify") as identify,
            patch.object(care_sessions, "careflow", create=True) as careflow,
        ):
            cry_gate.classify.side_effect = classify
            identify.return_value = self._selected_identity(profile["id"])
            careflow.preview_profile_incident.return_value = (
                self._no_guidance_preview(profile)
            )
            threads = [
                threading.Thread(target=submit, args=(ingested,))
                for ingested in (first, second)
            ]
            for thread in threads:
                thread.start()
            self.assertTrue(gate_started.wait(timeout=3))
            release_gate.set()
            for thread in threads:
                thread.join(timeout=5)

        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual([], errors)
        self.assertEqual(2, len(results))
        self.assertEqual(
            ["error", "matched_no_guidance"],
            sorted(
                result.get("chunk", result).get("status")
                for result in results
            ),
        )
        conflict = next(result for result in results if "chunk" not in result)
        self.assert_error(conflict, "sequence_conflict")
        self.assertEqual(1, cry_gate.classify.call_count)
        self.assertEqual(1, identify.call_count)
        self.assertEqual(1, careflow.preview_profile_incident.call_count)

    def test_chunk_inference_claim_is_released_after_unexpected_exception(self):
        profile = self._profile()
        session = care_sessions.create(profile["id"], db_path=self.db)
        ingested = self._ingested("claim-exception", b"retry-after-error")
        with (
            patch.object(
                care_sessions.identity,
                "get_profile",
                side_effect=[RuntimeError("unexpected profile read"), profile],
            ),
            patch.object(care_sessions, "cry_gate", create=True) as cry_gate,
            patch.object(care_sessions.identity, "identify") as identify,
            patch.object(care_sessions, "careflow", create=True) as careflow,
        ):
            cry_gate.classify.return_value = self._cry_result("infant_cry_detected")
            identify.return_value = self._selected_identity(profile["id"])
            careflow.preview_profile_incident.return_value = (
                self._no_guidance_preview(profile)
            )
            first = care_sessions.submit_chunk(
                session["id"],
                1,
                ingested,
                self.db,
            )
            second = care_sessions.submit_chunk(
                session["id"],
                1,
                ingested,
                self.db,
            )

        self.assert_error(first, "care_session_storage_error")
        self.assertEqual("matched_no_guidance", second["chunk"]["status"])
        self.assertEqual({}, care_sessions._CHUNK_INFERENCE_CLAIMS)

    def test_chunks_are_rejected_outside_listening_state(self):
        profile = self._profile()
        sessions = {}
        for state in ("paused", "awaiting_outcome", "complete", "discarded"):
            created = care_sessions.create(profile["id"], db_path=self.db)
            self._set_session_state(created["id"], state)
            sessions[state] = created

        with (
            patch.object(care_sessions, "cry_gate", create=True) as cry_gate,
            patch.object(care_sessions.identity, "identify") as identify,
        ):
            for state, session in sessions.items():
                with self.subTest(state=state):
                    result = care_sessions.submit_chunk(
                        session["id"],
                        1,
                        self._ingested(f"state-{state}"),
                        self.db,
                    )
                    self.assert_error(result, "invalid_care_session_transition")

        cry_gate.classify.assert_not_called()
        identify.assert_not_called()

    def test_invalid_ingest_and_nonpositive_sequences_fail_before_gate(self):
        profile = self._profile()
        session = care_sessions.create(profile["id"], db_path=self.db)
        with (
            patch.object(care_sessions, "cry_gate", create=True) as cry_gate,
            patch.object(care_sessions.identity, "identify") as identify,
        ):
            invalid_sequence = care_sessions.submit_chunk(
                session["id"],
                0,
                self._ingested("invalid-sequence"),
                self.db,
            )
            invalid_ingest = care_sessions.submit_chunk(
                session["id"],
                1,
                {
                    "status": "invalid",
                    "reason": "decode_failed",
                    "source_path": str(self.root / "managed" / "broken.webm"),
                    "sha256": "not-public",
                },
                self.db,
            )

        self.assert_error(invalid_sequence, "invalid_chunk_sequence")
        self.assertEqual("invalid", invalid_ingest["chunk"]["status"])
        self.assertEqual(["decode_failed"], invalid_ingest["chunk"]["reason_codes"])
        cry_gate.classify.assert_not_called()
        identify.assert_not_called()
        self.assertEqual(1, care_sessions.get(session["id"], self.db)["last_sequence"])

    def test_chunk_capture_time_precedes_inference_and_audit_metadata_is_persisted(self):
        profile = self._profile()
        session = care_sessions.create(profile["id"], db_path=self.db)
        ingested = self._ingested("audit", b"authoritative-source-bytes")
        events = []
        captured_at = "2026-07-30T03:15:00-04:00"

        def stamp():
            events.append("timestamp")
            return captured_at

        def classify(_audio_path):
            events.append("cry_gate")
            return self._cry_result("no_cry_detected")

        with (
            patch.object(care_sessions, "_now", side_effect=stamp),
            patch.object(care_sessions, "cry_gate", create=True) as cry_gate,
            patch.object(care_sessions.identity, "identify") as identify,
        ):
            cry_gate.classify.side_effect = classify
            result = care_sessions.submit_chunk(
                session["id"],
                1,
                ingested,
                self.db,
            )

        with sqlite3.connect(self.db) as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute(
                "SELECT * FROM care_session_chunk WHERE session_id=? AND sequence=1",
                (session["id"],),
            ).fetchone()

        self.assertEqual(["timestamp", "cry_gate"], events)
        self.assertEqual(captured_at, result["chunk"]["created_at"])
        self.assertEqual(captured_at, row["created_at"])
        self.assertEqual(
            hashlib.sha256(b"authoritative-source-bytes").hexdigest(),
            row["audio_sha256"],
        )
        self.assertNotEqual(ingested["sha256"], row["audio_sha256"])
        self.assertEqual(ingested["capture"], json.loads(row["capture_metadata_json"]))
        self.assertEqual(ingested["quality"], json.loads(row["quality_json"]))
        self.assertEqual(result, json.loads(row["result_json"]))
        identify.assert_not_called()

    def test_nonpositive_cry_gate_results_never_run_identity_or_history(self):
        profile = self._profile()
        with (
            patch.object(care_sessions, "cry_gate", create=True) as cry_gate,
            patch.object(care_sessions.identity, "identify") as identify,
            patch.object(care_sessions, "careflow", create=True) as careflow,
        ):
            for index, gate_status in enumerate(
                ("no_cry_detected", "cry_uncertain", "gate_unavailable"),
                start=1,
            ):
                session = care_sessions.create(profile["id"], db_path=self.db)
                cry_gate.classify.return_value = self._cry_result(gate_status)
                result = care_sessions.submit_chunk(
                    session["id"],
                    1,
                    self._ingested(f"gate-{index}"),
                    self.db,
                )
                expected = "invalid" if gate_status == "gate_unavailable" else gate_status
                self.assertEqual(expected, result["chunk"]["status"])
                self.assertEqual(
                    {
                        key: value
                        for key, value in self._cry_result(gate_status).items()
                        if key
                        in {
                            "status",
                            "label",
                            "reason_codes",
                            "analyzed_duration_s",
                            "analysis_view_count",
                            "model_version",
                        }
                    },
                    result["chunk"]["cry_presence"],
                )

        identify.assert_not_called()
        careflow.preview_profile_incident.assert_not_called()

    def test_only_selected_profile_match_can_read_history_and_chunks_never_enroll(self):
        selected = self._profile("Baby A")
        other = self._profile("Baby B")
        with (
            patch.object(care_sessions, "cry_gate", create=True) as cry_gate,
            patch.object(care_sessions.identity, "identify") as identify,
            patch.object(care_sessions.identity, "enroll") as enroll,
            patch.object(care_sessions.identity, "create_profile") as create_profile,
            patch.object(care_sessions, "careflow", create=True) as careflow,
        ):
            cry_gate.classify.return_value = self._cry_result("infant_cry_detected")
            identify.side_effect = [
                self._selected_identity(other["id"]),
                {
                    "status": "uncertain",
                    "reasons": ["below_accept_threshold"],
                    "score": 0.7,
                    "margin": 0.01,
                    "candidates": [{"profile_id": selected["id"]}],
                },
                self._selected_identity(selected["id"]),
            ]
            careflow.preview_profile_incident.return_value = self._no_guidance_preview(
                selected
            )
            results = []
            for name in ("other", "uncertain", "selected"):
                session = care_sessions.create(selected["id"], db_path=self.db)
                results.append(
                    care_sessions.submit_chunk(
                        session["id"],
                        1,
                        self._ingested(f"identity-{name}"),
                        self.db,
                    )
                )

        self.assertEqual(
            ["not_selected_profile", "not_selected_profile", "matched_no_guidance"],
            [result["chunk"]["status"] for result in results],
        )
        self.assertEqual(3, identify.call_count)
        for call, name in zip(identify.call_args_list, ("other", "uncertain", "selected")):
            self.assertEqual(
                (
                    str(self.root / "managed" / f"identity-{name}" / "identity.wav"),
                ),
                call.args,
            )
            self.assertEqual(
                {"kind": "infant", "db_path": self.db, "audit": True},
                call.kwargs,
            )
        careflow.preview_profile_incident.assert_called_once_with(
            selected["id"],
            str(self.root / "managed" / "identity-selected" / "identity.wav"),
            explicit_tags=[],
            now=results[2]["chunk"]["created_at"],
            db_path=self.db,
        )
        enroll.assert_not_called()
        create_profile.assert_not_called()

    def test_demo_baby_accepts_strong_close_top_match_at_demo_margin(self):
        selected = self._profile("Demo Baby")
        other = self._profile("Learning Baby")
        care_session = care_sessions.create(selected["id"], db_path=self.db)
        preview = self._no_guidance_preview(selected)
        preview["guidance"] = {
            "status": "grounded",
            "headline": "What helped before",
            "interpretation": "This resembles an earlier incident.",
            "recommendation": "What helped before: turned on white noise.",
            "evidence_summary": "Supported by 1 similar recorded incident.",
            "support_count": 1,
            "incident_ids": [101],
        }
        uncertain = {
            "status": "uncertain",
            "profile_id": None,
            "score": 0.91,
            "margin": 0.05,
            "candidates": [
                {"profile_id": selected["id"], "score": 0.91},
                {"profile_id": other["id"], "score": 0.86},
            ],
            "reasons": ["close_top_profiles"],
        }
        with (
            patch.object(care_sessions, "cry_gate", create=True) as cry_gate,
            patch.object(care_sessions.identity, "identify") as identify,
            patch.object(care_sessions, "careflow", create=True) as careflow,
        ):
            cry_gate.classify.return_value = self._cry_result("infant_cry_detected")
            identify.return_value = uncertain
            careflow.preview_profile_incident.return_value = preview
            result = care_sessions.submit_chunk(
                care_session["id"],
                1,
                self._ingested("demo-strong-close-top"),
                self.db,
            )

        self.assertEqual("guidance_latched", result["chunk"]["status"])
        self.assertEqual(
            "What helped before: turned on white noise.",
            result["session"]["decision"]["guidance"]["recommendation"],
        )
        with sqlite3.connect(self.db) as connection:
            stored = connection.execute(
                "SELECT matched_profile_id FROM care_session_chunk "
                "WHERE session_id=? AND sequence=1",
                (care_session["id"],),
            ).fetchone()
        self.assertEqual((selected["id"],), stored)

    def test_demo_margin_does_not_change_other_profiles_or_weak_margins(self):
        demo = self._profile("Demo Baby")
        other = self._profile("Baby A")
        cases = (
            (demo, 0.02, "demo-too-close"),
            (other, 0.05, "ordinary-profile"),
        )
        results = []
        with (
            patch.object(care_sessions, "cry_gate", create=True) as cry_gate,
            patch.object(care_sessions.identity, "identify") as identify,
            patch.object(care_sessions, "careflow", create=True) as careflow,
        ):
            cry_gate.classify.return_value = self._cry_result("infant_cry_detected")
            careflow.preview_profile_incident.return_value = self._no_guidance_preview(demo)
            for selected, margin, name in cases:
                care_session = care_sessions.create(selected["id"], db_path=self.db)
                identify.return_value = {
                    "status": "uncertain",
                    "profile_id": None,
                    "score": 0.91,
                    "margin": margin,
                    "candidates": [
                        {"profile_id": selected["id"], "score": 0.91},
                        {"profile_id": demo["id"], "score": 0.91 - margin},
                    ],
                    "reasons": ["close_top_profiles"],
                }
                results.append(
                    care_sessions.submit_chunk(
                        care_session["id"],
                        1,
                        self._ingested(name),
                        self.db,
                    )
                )

        self.assertEqual(
            ["not_selected_profile", "not_selected_profile"],
            [result["chunk"]["status"] for result in results],
        )
        careflow.preview_profile_incident.assert_not_called()

    def test_live_retrieval_uses_normalized_audio_and_keeps_canonical_evidence(self):
        profile = self._profile("Baby A")
        care_session = care_sessions.create(profile["id"], db_path=self.db)
        ingested = self._ingested("quiet-live-selected")
        with (
            patch.object(care_sessions, "cry_gate", create=True) as cry_gate,
            patch.object(care_sessions.identity, "identify") as identify,
            patch.object(care_sessions, "careflow", create=True) as careflow,
        ):
            cry_gate.classify.return_value = self._cry_result("infant_cry_detected")
            identify.return_value = self._selected_identity(profile["id"])
            careflow.preview_profile_incident.return_value = (
                self._no_guidance_preview(profile)
            )
            result = care_sessions.submit_chunk(
                care_session["id"],
                1,
                ingested,
                self.db,
            )

        self.assertEqual("matched_no_guidance", result["chunk"]["status"])
        careflow.preview_profile_incident.assert_called_once_with(
            profile["id"],
            ingested["identity_path"],
            explicit_tags=[],
            now=result["chunk"]["created_at"],
            db_path=self.db,
        )
        with sqlite3.connect(self.db) as connection:
            stored = connection.execute(
                "SELECT canonical_audio_path, identity_audio_path "
                "FROM care_session_chunk WHERE session_id=? AND sequence=1",
                (care_session["id"],),
            ).fetchone()
        self.assertEqual(
            (ingested["canonical_path"], ingested["identity_path"]),
            stored,
        )

    def test_first_grounded_guidance_latches_and_later_guidance_cannot_replace_it(self):
        profile = self._profile("Baby A")
        session = care_sessions.create(profile["id"], ["evening"], self.db)
        scenario_a = {
            "episode_id": 101,
            "started_at": "2026-07-27T20:04:00-04:00",
            "interventions": [
                {
                    "order": 1,
                    "action": "held baby upright",
                    "evidence": "held baby upright",
                    "score": 0.99,
                }
            ],
            "outcome": "The baby settled.",
            "outcome_src": "caregiver",
            "worked": True,
            "contributions": [
                "cry pattern was the strongest available signal",
                "occurred at a similar time of day",
            ],
            "audio_url": f"/api/profiles/{profile['id']}/incidents/101/audio",
            "components": {"score": 4.0},
            "audio_path": "/private/episode.wav",
            "embedding": [1.0],
        }
        scenario_b = {
            **scenario_a,
            "episode_id": 202,
            "interventions": [
                {
                    "order": 1,
                    "action": "walked around the room",
                    "evidence": "walked around the room",
                }
            ],
            "audio_url": f"/api/profiles/{profile['id']}/incidents/202/audio",
        }
        no_guidance = self._no_guidance_preview(profile)
        guidance_a = {
            "status": "preview",
            "identity": no_guidance["identity"],
            "scenarios": [scenario_a],
            "guidance": {
                "status": "grounded",
                "headline": "What helped before",
                "interpretation": "This resembles earlier incidents.",
                "recommendation": "What helped before: held baby upright.",
                "evidence_summary": "Supported by 1 similar recorded incident.",
                "action": "held baby upright",
                "support_count": 1,
                "incident_ids": [101],
                "outcomes": [
                    {
                        "incident_id": 101,
                        "text": "settled",
                        "source": "caregiver",
                    }
                ],
                "pattern": "similar time of day",
                "score": 0.99,
            },
        }
        guidance_b = {
            **guidance_a,
            "scenarios": [scenario_b],
            "guidance": {
                **guidance_a["guidance"],
                "recommendation": "What helped before: walked around the room.",
                "action": "walked around the room",
                "incident_ids": [202],
            },
        }
        with (
            patch.object(care_sessions, "cry_gate", create=True) as cry_gate,
            patch.object(care_sessions.identity, "identify") as identify,
            patch.object(care_sessions, "careflow", create=True) as careflow,
        ):
            cry_gate.classify.return_value = self._cry_result("infant_cry_detected")
            identify.return_value = self._selected_identity(profile["id"])
            careflow.preview_profile_incident.side_effect = [
                no_guidance,
                guidance_a,
                guidance_b,
            ]
            first = care_sessions.submit_chunk(
                session["id"],
                1,
                self._ingested("latch-1", b"one"),
                self.db,
            )
            second = care_sessions.submit_chunk(
                session["id"],
                2,
                self._ingested("latch-2", b"two"),
                self.db,
            )
            third = care_sessions.submit_chunk(
                session["id"],
                3,
                self._ingested("latch-3", b"three"),
                self.db,
            )

        self.assertEqual("matched_no_guidance", first["chunk"]["status"])
        self.assertEqual("guidance_latched", second["chunk"]["status"])
        self.assertEqual(
            "matched_guidance_already_latched",
            third["chunk"]["status"],
        )
        decision = third["session"]["decision"]
        self.assertEqual(
            "What helped before: held baby upright.",
            decision["guidance"]["recommendation"],
        )
        self.assertEqual([101], decision["guidance"]["incident_ids"])
        self.assertEqual([101], [item["episode_id"] for item in decision["scenarios"]])
        self.assertEqual(
            f"/api/profiles/{profile['id']}/incidents/101/audio",
            decision["scenarios"][0]["audio_url"],
        )
        self.assertEqual(second["chunk"]["id"], decision["id"])
        self.assertEqual(
            second["chunk"]["id"],
            self._session_db_value(session["id"], "selected_chunk_id"),
        )
        self.assertEqual(
            third["chunk"]["id"],
            self._session_db_value(session["id"], "latest_matched_chunk_id"),
        )
        self.assert_public_result_has_no_sensitive_analysis(first)
        self.assert_public_result_has_no_sensitive_analysis(second)
        self.assert_public_result_has_no_sensitive_analysis(third)

    def test_complete_requires_stop_and_a_representative_matched_chunk(self):
        profile = self._profile()
        listening = care_sessions.create(profile["id"], db_path=self.db)
        self._insert_matched_chunk(
            listening["id"],
            profile["id"],
            1,
            "2026-07-30T11:00:00-04:00",
            "listening",
        )

        before_stop = care_sessions.complete(
            listening["id"],
            "Held baby upright",
            True,
            db_path=self.db,
        )

        no_match = care_sessions.create(profile["id"], db_path=self.db)
        care_sessions.stop(no_match["id"], self.db)
        without_chunk = care_sessions.complete(
            no_match["id"],
            "Held baby upright",
            True,
            db_path=self.db,
        )

        self.assert_error(before_stop, "invalid_care_session_transition")
        self.assert_error(without_chunk, "no_matched_chunk")
        self.assertEqual([], store.list_episodes(f"profile-{profile['id']}", self.db))

    def test_complete_uses_selected_chunk_and_returns_only_safe_incident_reference(self):
        profile = self._profile()
        care_session = care_sessions.create(
            profile["id"],
            tags=[" Evening ", "evening"],
            db_path=self.db,
        )
        selected = self._insert_matched_chunk(
            care_session["id"],
            profile["id"],
            1,
            "2026-07-30T11:00:00-04:00",
            "selected",
        )
        latest = self._insert_matched_chunk(
            care_session["id"],
            profile["id"],
            2,
            "2026-07-30T12:00:00-04:00",
            "latest",
        )
        with sqlite3.connect(self.db) as connection:
            connection.execute(
                "UPDATE care_session SET selected_chunk_id=?, "
                "latest_matched_chunk_id=? WHERE id=?",
                (selected["id"], latest["id"], care_session["id"]),
            )
        care_sessions.stop(care_session["id"], self.db)
        care_events = [
            {
                "id": 91,
                "profile_id": profile["id"],
                "event_type": "feeding",
                "occurred_at": "2026-07-30T10:30:00-04:00",
                "details": {},
            }
        ]

        with (
            patch.object(
                care_sessions.context.store,
                "list_care_events",
                return_value=care_events,
                create=True,
            ),
            patch.object(
                care_sessions.session.fingerprint,
                "compute_windowed",
                return_value=[0.0] * 87,
            ),
            patch.object(
                care_sessions.session.fingerprint,
                "duration_s",
                return_value=5.0,
            ),
            patch.object(
                care_sessions.session.speech,
                "transcribe",
                return_value="I picked her up.",
            ),
            patch.object(
                care_sessions.session.speech,
                "extract_interventions",
                return_value=[],
            ),
        ):
            result = care_sessions.complete(
                care_session["id"],
                "  Held baby upright  ",
                False,
                notes="  Still crying  ",
                tags=[" At Home ", "EVENING"],
                db_path=self.db,
            )

        episodes = store.list_episodes(f"profile-{profile['id']}", self.db)
        self.assertEqual(1, len(episodes))
        episode = episodes[0]
        self.assertEqual(selected["canonical_path"], episode["audio_path"])
        self.assertEqual(selected["created_at"], episode["started_at"])
        self.assertIs(episode["worked"], False)
        self.assertEqual(
            {
                "hour_local": 11,
                "tags": ["evening", "at home", "last_feed_under_2h"],
                "care_event_ids": [91],
                "care_session_id": care_session["id"],
                "selected_chunk_id": selected["id"],
                "profile_id": profile["id"],
            },
            episode["context"],
        )
        expected = {
            "session": care_sessions.get(care_session["id"], self.db),
            "incident": {
                "id": episode["id"],
                "detail_url": (
                    f"/api/profiles/{profile['id']}/incidents/{episode['id']}"
                ),
            },
        }
        self.assertEqual(expected, result)
        self.assertEqual({"id", "detail_url"}, set(result["incident"]))
        self.assertNotIn("episode", result)

    def test_complete_falls_back_to_latest_matched_chunk_and_is_idempotent(self):
        profile = self._profile()
        care_session = care_sessions.create(profile["id"], db_path=self.db)
        latest = self._insert_matched_chunk(
            care_session["id"],
            profile["id"],
            1,
            "2026-07-30T12:30:00-04:00",
            "latest-only",
        )
        care_sessions.stop(care_session["id"], self.db)

        with (
            patch.object(
                care_sessions.session.fingerprint,
                "compute_windowed",
                return_value=[0.0] * 87,
            ),
            patch.object(
                care_sessions.session.fingerprint,
                "duration_s",
                return_value=5.0,
            ),
            patch.object(
                care_sessions.session.speech,
                "transcribe",
                return_value="",
            ) as transcribe,
        ):
            first = care_sessions.complete(
                care_session["id"],
                "Held baby upright",
                None,
                db_path=self.db,
            )
            second = care_sessions.complete(
                care_session["id"],
                "",
                1,
                notes="different",
                db_path=self.db,
            )

        episodes = store.list_episodes(f"profile-{profile['id']}", self.db)
        self.assertEqual(1, len(episodes))
        self.assertEqual(latest["id"], episodes[0]["context"]["selected_chunk_id"])
        self.assertEqual(latest["created_at"], episodes[0]["started_at"])
        self.assertEqual(first, second)
        transcribe.assert_called_once_with(latest["canonical_path"])

    def test_complete_recovers_one_saved_episode_after_a_transient_attach_failure(self):
        profile = self._profile()
        care_session = care_sessions.create(profile["id"], db_path=self.db)
        self._insert_matched_chunk(
            care_session["id"],
            profile["id"],
            1,
            "2026-07-30T13:00:00-04:00",
            "recover",
        )
        care_sessions.stop(care_session["id"], self.db)
        real_attach = care_sessions._attach_completed_episode
        attach_calls = 0

        def fail_once(*args, **kwargs):
            nonlocal attach_calls
            attach_calls += 1
            if attach_calls == 1:
                return False
            return real_attach(*args, **kwargs)

        with (
            patch.object(
                care_sessions,
                "_attach_completed_episode",
                side_effect=fail_once,
            ),
            patch.object(
                care_sessions.session.fingerprint,
                "compute_windowed",
                return_value=[0.0] * 87,
            ),
            patch.object(
                care_sessions.session.fingerprint,
                "duration_s",
                return_value=5.0,
            ),
            patch.object(
                care_sessions.session.speech,
                "transcribe",
                return_value="",
            ),
        ):
            result = care_sessions.complete(
                care_session["id"],
                "Held baby upright",
                True,
                db_path=self.db,
            )

        episodes = store.list_episodes(f"profile-{profile['id']}", self.db)
        self.assertEqual(2, attach_calls)
        self.assertEqual(1, len(episodes))
        self.assertEqual(episodes[0]["id"], result["incident"]["id"])
        self.assertEqual("complete", result["session"]["status"])

    def test_concurrent_complete_calls_save_and_transcribe_exactly_once(self):
        profile = self._profile()
        care_session = care_sessions.create(profile["id"], db_path=self.db)
        selected = self._insert_matched_chunk(
            care_session["id"],
            profile["id"],
            1,
            "2026-07-30T14:00:00-04:00",
            "concurrent",
        )
        care_sessions.stop(care_session["id"], self.db)
        transcribe_entered = threading.Event()
        release_transcribe = threading.Event()
        results = []
        thread_errors = []

        def slow_transcribe(path):
            self.assertEqual(selected["canonical_path"], path)
            transcribe_entered.set()
            if not release_transcribe.wait(timeout=3):
                raise AssertionError("test did not release transcription")
            return ""

        def run_complete():
            try:
                results.append(
                    care_sessions.complete(
                        care_session["id"],
                        "Held baby upright",
                        True,
                        db_path=self.db,
                    )
                )
            except BaseException as exc:
                thread_errors.append(exc)

        with (
            patch.object(
                care_sessions.session.fingerprint,
                "compute_windowed",
                return_value=[0.0] * 87,
            ),
            patch.object(
                care_sessions.session.fingerprint,
                "duration_s",
                return_value=5.0,
            ),
            patch.object(
                care_sessions.session.speech,
                "transcribe",
                side_effect=slow_transcribe,
            ) as transcribe,
        ):
            first = threading.Thread(target=run_complete)
            second = threading.Thread(target=run_complete)
            first.start()
            self.assertTrue(transcribe_entered.wait(timeout=3))
            second.start()
            release_transcribe.set()
            first.join(timeout=5)
            second.join(timeout=5)

        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertEqual([], thread_errors)
        self.assertEqual(2, len(results))
        self.assertEqual(results[0], results[1])
        self.assertEqual(
            1,
            len(store.list_episodes(f"profile-{profile['id']}", self.db)),
        )
        self.assertEqual(1, transcribe.call_count)

    def test_completion_failure_releases_claim_for_a_clean_retry(self):
        profile = self._profile()
        care_session = care_sessions.create(profile["id"], db_path=self.db)
        self._insert_matched_chunk(
            care_session["id"],
            profile["id"],
            1,
            "2026-07-30T14:30:00-04:00",
            "retry-after-error",
        )
        care_sessions.stop(care_session["id"], self.db)

        with patch.object(
            care_sessions.context,
            "build_current_context",
            side_effect=RuntimeError("context backend failed"),
        ):
            failed = care_sessions.complete(
                care_session["id"],
                "Held baby upright",
                True,
                db_path=self.db,
            )

        with (
            patch.object(
                care_sessions.session.fingerprint,
                "compute_windowed",
                return_value=[0.0] * 87,
            ),
            patch.object(
                care_sessions.session.fingerprint,
                "duration_s",
                return_value=5.0,
            ),
            patch.object(
                care_sessions.session.speech,
                "transcribe",
                return_value="",
            ),
        ):
            retried = care_sessions.complete(
                care_session["id"],
                "Held baby upright",
                True,
                db_path=self.db,
            )

        self.assert_error(failed, "care_session_storage_error")
        self.assertEqual("complete", retried["session"]["status"])

    def test_discard_waits_for_completion_transcription_and_cannot_remove_saved_audio(self):
        profile = self._profile()
        care_session = care_sessions.create(profile["id"], db_path=self.db)
        selected = self._insert_matched_chunk(
            care_session["id"],
            profile["id"],
            1,
            "2026-07-30T15:00:00-04:00",
            "complete-discard",
        )
        care_sessions.stop(care_session["id"], self.db)
        transcribe_entered = threading.Event()
        release_transcribe = threading.Event()
        complete_results = []
        discard_results = []

        def slow_transcribe(path):
            transcribe_entered.set()
            if not release_transcribe.wait(timeout=3):
                raise AssertionError("test did not release transcription")
            return ""

        with (
            patch.object(
                care_sessions.session.fingerprint,
                "compute_windowed",
                return_value=[0.0] * 87,
            ),
            patch.object(
                care_sessions.session.fingerprint,
                "duration_s",
                return_value=5.0,
            ),
            patch.object(
                care_sessions.session.speech,
                "transcribe",
                side_effect=slow_transcribe,
            ),
        ):
            completion_thread = threading.Thread(
                target=lambda: complete_results.append(
                    care_sessions.complete(
                        care_session["id"],
                        "Held baby upright",
                        True,
                        db_path=self.db,
                    )
                )
            )
            discard_thread = threading.Thread(
                target=lambda: discard_results.append(
                    care_sessions.discard(
                        care_session["id"],
                        self.root / "managed",
                        self.db,
                    )
                )
            )
            completion_thread.start()
            self.assertTrue(transcribe_entered.wait(timeout=3))
            discard_thread.start()
            discard_thread.join(timeout=0.1)
            self.assertTrue(discard_thread.is_alive())
            self.assertTrue(Path(selected["canonical_path"]).exists())
            release_transcribe.set()
            completion_thread.join(timeout=5)
            discard_thread.join(timeout=5)

        self.assertEqual("complete", complete_results[0]["session"]["status"])
        self.assert_error(discard_results[0], "invalid_care_session_transition")
        self.assertTrue(Path(selected["canonical_path"]).exists())

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
