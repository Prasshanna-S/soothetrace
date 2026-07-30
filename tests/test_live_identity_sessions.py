"""Public acoustic helper boundaries for incremental live identity sessions."""
from __future__ import annotations

import math
import os
import sqlite3
import struct
import sys
import tempfile
import unittest
import wave
from unittest.mock import patch

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

import config  # noqa: E402
import encoders  # noqa: E402
import fingerprint  # noqa: E402
import identity  # noqa: E402
import live_sessions  # noqa: E402
import store  # noqa: E402


def tone_wav(path, frequency):
    frames = bytearray()
    for i in range(16000):
        value = 0.3 * math.sin(2 * math.pi * frequency * i / 16000)
        frames += struct.pack("<h", int(value * 32767))
    with wave.open(path, "wb") as fh:
        fh.setnchannels(1)
        fh.setsampwidth(2)
        fh.setframerate(16000)
        fh.writeframes(bytes(frames))
    return path


class LiveIdentityHelperTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self._tmp.name, "identity.db")
        store.init_db(self.db)
        store.save_baseline(config.POPULATION_KEY, [0.0] * fingerprint.DIM,
                            [1.0] * fingerprint.DIM, 1, self.db)
        self._vectors = {}

    def tearDown(self):
        self._tmp.cleanup()

    def wav(self, name, frequency):
        return tone_wav(os.path.join(self._tmp.name, name), frequency)

    def _encode(self, encoder_name, audio_path):
        base = self._vectors[os.path.basename(audio_path)]
        dimensions = encoders.dim(encoder_name)
        vector = np.zeros(dimensions)
        vector[base] = 1.0
        return vector.tolist()

    def _enroll(self, profile, name, frequency, vector_index):
        path = self.wav(name, frequency)
        self._vectors[name] = vector_index
        self.assertEqual(
            "enrolled",
            identity.enroll(profile["id"], path, db_path=self.db)["status"],
        )
        return path

    def _assert_no_acoustic_metrics(self, value):
        forbidden = {"score", "scores", "margin", "similarity", "confidence"}
        if isinstance(value, dict):
            for key, child in value.items():
                self.assertNotIn(key.lower(), forbidden)
                self._assert_no_acoustic_metrics(child)
        elif isinstance(value, list):
            for child in value:
                self._assert_no_acoustic_metrics(child)

    def test_identify_within_profiles_excludes_unrelated_profile_candidates(self):
        """A session profile filter must prevent another profile entering the scored pool."""
        with patch.object(identity.encoders, "encode", side_effect=self._encode):
            session_profile = identity.create_profile(
                "Session person", identity.KIND_IMITATION, self.db
            )
            unrelated_profile = identity.create_profile(
                "Unrelated person", identity.KIND_IMITATION, self.db
            )
            self._enroll(session_profile, "session-1.wav", 400, 0)
            self._enroll(unrelated_profile, "unrelated-1.wav", 800, 1)
            query_path = self.wav("query.wav", 410)
            self._vectors["query.wav"] = 0

            result = identity.identify_within_profiles(
                query_path,
                [session_profile["id"]],
                identity.KIND_IMITATION,
                self.db,
                audit=False,
            )

        self.assertNotIn(unrelated_profile["id"], [
            item["profile_id"] for item in result.get("candidates", [])
        ])
        self.assertEqual(1, result["pool_size"])
        self._assert_no_acoustic_metrics(result)

    def test_recordings_consistent_hides_raw_scores_directly(self):
        """The session-facing pair helper itself must not leak acoustic scores."""
        first_path = self.wav("first.wav", 400)
        second_path = self.wav("second.wav", 405)
        self._vectors.update({"first.wav": 0, "second.wav": 0})

        with patch.object(identity.encoders, "encode", side_effect=self._encode):
            pair = identity.recordings_consistent(
                first_path,
                second_path,
                identity.KIND_IMITATION,
                self.db,
            )

        self.assertIn("consistent", pair)
        self.assertEqual({"consistent", "version", "reasons"}, set(pair))
        self._assert_no_acoustic_metrics(pair)

    def test_recordings_consistent_many_reuses_query_and_hides_raw_scores(self):
        first_path = self.wav("first.wav", 400)
        other_path = self.wav("other.wav", 800)
        query_path = self.wav("query.wav", 405)
        self._vectors.update({"first.wav": 0, "other.wav": 1, "query.wav": 0})

        with patch.object(
            identity.encoders,
            "encode",
            side_effect=self._encode,
        ) as encode:
            results = identity.recordings_consistent_many(
                [first_path, other_path],
                query_path,
                identity.KIND_IMITATION,
                self.db,
            )

        self.assertEqual([True, False], [result["consistent"] for result in results])
        self.assertTrue(all(
            set(result) == {"consistent", "version", "reasons"}
            for result in results
        ))
        self.assertEqual(
            2,
            sum(
                call.args[1] == query_path
                for call in encode.call_args_list
            ),
        )
        self._assert_no_acoustic_metrics(results)

    def test_profile_reference_audio_returns_only_that_profiles_paths(self):
        """Session playback can retrieve references without exposing enrollment embeddings."""
        with patch.object(identity.encoders, "encode", side_effect=self._encode):
            target = identity.create_profile("Target", identity.KIND_IMITATION, self.db)
            other = identity.create_profile("Other", identity.KIND_IMITATION, self.db)
            target_path = self._enroll(target, "target.wav", 400, 0)
            self._enroll(other, "other.wav", 800, 1)

        self.assertEqual([target_path], identity.profile_reference_audio(target["id"], self.db))


class LiveIdentityStateTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self._tmp.name, "identity.db")
        store.init_db(self.db)
        store.save_baseline(
            config.POPULATION_KEY,
            [0.0] * fingerprint.DIM,
            [1.0] * fingerprint.DIM,
            1,
            self.db,
        )
        self._vectors = {}

    def tearDown(self):
        self._tmp.cleanup()

    def wav(self, name, frequency):
        return tone_wav(os.path.join(self._tmp.name, name), frequency)

    def _encode(self, encoder_name, audio_path):
        vector = np.zeros(encoders.dim(encoder_name))
        vector[self._vectors[os.path.basename(audio_path)]] = 1.0
        return vector.tolist()

    def _audio(self, name, frequency, vector_index):
        path = self.wav(name, frequency)
        self._vectors[name] = vector_index
        return path

    def _persistence_state(self):
        tables = (
            "profile",
            "enrollment",
            "live_identity_participant",
            "live_identity_observation",
        )
        with sqlite3.connect(self.db) as connection:
            return {
                table: connection.execute(
                    f"SELECT * FROM {table} ORDER BY id"
                ).fetchall()
                for table in tables
            }

    @staticmethod
    def _batch_pairs(pair):
        def compare(reference_paths, query_path, kind, db_path=None):
            return [
                pair(reference_path, query_path, kind, db_path)
                for reference_path in reference_paths
            ]

        return compare

    def _assert_public(self, value):
        forbidden_fragments = (
            "path",
            "sha",
            "digest",
            "embedding",
            "score",
            "margin",
            "similarity",
            "confidence",
            "candidate",
        )
        if isinstance(value, dict):
            for key, child in value.items():
                lowered = key.lower()
                self.assertFalse(
                    any(fragment in lowered for fragment in forbidden_fragments),
                    f"private key leaked: {key}",
                )
                self._assert_public(child)
        elif isinstance(value, list):
            for child in value:
                self._assert_public(child)

    def test_first_observation_is_provisional_and_consistent_second_establishes(self):
        session = live_sessions.create(db_path=self.db)
        first_path = self._audio("first.wav", 400, 0)
        second_path = self._audio("second.wav", 405, 0)

        with (
            patch.object(identity.encoders, "encode", side_effect=self._encode),
            patch.object(
                identity,
                "recordings_consistent_many",
                side_effect=self._batch_pairs(
                    lambda first, second, kind, db_path=None: {
                        "consistent": True,
                        "version": "pair-v1",
                        "reasons": ["novelty_pair_consistent"],
                    }
                ),
            ),
        ):
            first = live_sessions.submit_observation(
                session["id"],
                first_path,
                {"capture_source": "microphone"},
                db_path=self.db,
            )
            self.assertEqual("provisional_created", first["classification"]["status"])
            self.assertEqual("microphone", first["observation"]["source_type"])
            self.assertEqual(
                "Person A",
                first["classification"]["participant"]["display_name"],
            )
            self.assertEqual(
                "provisional",
                first["classification"]["participant"]["state"],
            )

            second = live_sessions.submit_observation(
                session["id"], second_path, db_path=self.db
            )

        self.assertEqual("participant", second["classification"]["status"])
        self.assertEqual(
            "established",
            second["classification"]["participant"]["state"],
        )
        self.assertTrue(second["classification"]["reinforced"])
        self.assertEqual(2, second["classification"]["participant"]["support_count"])
        self.assertEqual(
            f"/api/audio/live-observations/{second['observation']['id']}",
            second["observation"]["playback_url"],
        )
        self.assertEqual(
            second_path,
            live_sessions.observation_audio_path(second["observation"]["id"], self.db),
        )
        self._assert_public(first)
        self._assert_public(second)
        self._assert_public(live_sessions.get(session["id"], self.db))

    def test_new_session_can_reuse_a_recording_from_an_earlier_session(self):
        first_session = live_sessions.create(db_path=self.db)
        second_session = live_sessions.create(db_path=self.db)
        audio_path = self._audio("reusable.wav", 400, 0)

        with patch.object(identity.encoders, "encode", side_effect=self._encode):
            first = live_sessions.submit_observation(
                first_session["id"],
                audio_path,
                db_path=self.db,
            )
            second = live_sessions.submit_observation(
                second_session["id"],
                audio_path,
                db_path=self.db,
            )

        self.assertEqual("provisional_created", first["classification"]["status"])
        self.assertEqual("provisional_created", second["classification"]["status"])
        self.assertEqual(
            "Person A",
            second["classification"]["participant"]["display_name"],
        )
        self.assertNotEqual(
            first["classification"]["participant"]["profile_id"],
            second["classification"]["participant"]["profile_id"],
        )

    def test_new_participant_requires_consistent_pending_outlier_pair(self):
        session = live_sessions.create(db_path=self.db)
        first_path = self._audio("a-1.wav", 400, 0)
        second_path = self._audio("a-2.wav", 405, 0)
        different_first = self._audio("b-1.wav", 800, 1)
        different_second = self._audio("b-2.wav", 805, 1)

        def pair(first, second, kind, db_path=None):
            first_prefix = os.path.basename(first).split("-", 1)[0]
            second_prefix = os.path.basename(second).split("-", 1)[0]
            consistent = first_prefix == second_prefix
            return {
                "consistent": consistent,
                "version": "pair-v1",
                "reasons": [
                    "novelty_pair_consistent"
                    if consistent
                    else "novelty_pair_inconsistent"
                ],
            }

        with (
            patch.object(identity.encoders, "encode", side_effect=self._encode),
            patch.object(
                identity,
                "recordings_consistent_many",
                side_effect=self._batch_pairs(pair),
            ),
        ):
            live_sessions.submit_observation(session["id"], first_path, db_path=self.db)
            live_sessions.submit_observation(session["id"], second_path, db_path=self.db)
            pending = live_sessions.submit_observation(
                session["id"], different_first, db_path=self.db
            )
            created = live_sessions.submit_observation(
                session["id"], different_second, db_path=self.db
            )

        self.assertEqual("possible_new", pending["classification"]["status"])
        self.assertEqual(
            ["Person A"],
            [
                participant["display_name"]
                for participant in pending["session"]["participants"]
            ],
        )
        self.assertEqual("participant", created["classification"]["status"])
        self.assertEqual(
            "Person B", created["classification"]["participant"]["display_name"]
        )
        self.assertEqual(
            "established", created["classification"]["participant"]["state"]
        )
        self.assertEqual(2, created["classification"]["participant"]["support_count"])
        self.assertTrue(created["classification"]["reinforced"])

    def test_failed_participant_insert_removes_only_new_profile_and_enrollment(self):
        session = live_sessions.create(db_path=self.db)
        paths = {
            name: self._audio(f"{name}.wav", frequency, vector_index)
            for name, frequency, vector_index in (
                ("a-1", 400, 0),
                ("a-2", 405, 0),
                ("b-1", 800, 1),
                ("b-2", 805, 1),
            )
        }

        def pair(first, second, kind, db_path=None):
            first_prefix = os.path.basename(first).split("-", 1)[0]
            second_prefix = os.path.basename(second).split("-", 1)[0]
            consistent = first_prefix == second_prefix
            return {
                "consistent": consistent,
                "version": "pair-v1",
                "reasons": [
                    "novelty_pair_consistent"
                    if consistent
                    else "novelty_pair_inconsistent"
                ],
            }

        with (
            patch.object(identity.encoders, "encode", side_effect=self._encode),
            patch.object(
                identity,
                "recordings_consistent_many",
                side_effect=self._batch_pairs(pair),
            ),
        ):
            live_sessions.submit_observation(
                session["id"], paths["a-1"], db_path=self.db
            )
            live_sessions.submit_observation(
                session["id"], paths["a-2"], db_path=self.db
            )
            live_sessions.submit_observation(
                session["id"], paths["b-1"], db_path=self.db
            )
            before = self._persistence_state()
            with sqlite3.connect(self.db) as connection:
                connection.execute(
                    "CREATE TRIGGER fail_person_b_participant "
                    "BEFORE INSERT ON live_identity_participant "
                    "WHEN NEW.display_name='Person B' "
                    "BEGIN "
                    "SELECT RAISE(ABORT, 'injected participant insert failure'); "
                    "END"
                )
            result = live_sessions.submit_observation(
                session["id"], paths["b-2"], db_path=self.db
            )

        self.assertEqual({}, result)
        self.assertEqual(before, self._persistence_state())

    def test_failed_participant_update_restores_pre_submit_state(self):
        session = live_sessions.create(db_path=self.db)
        first_path = self._audio("a-1.wav", 400, 0)
        second_path = self._audio("a-2.wav", 405, 0)
        consistent = {
            "consistent": True,
            "version": "pair-v1",
            "reasons": ["novelty_pair_consistent"],
        }

        with (
            patch.object(identity.encoders, "encode", side_effect=self._encode),
            patch.object(
                identity,
                "recordings_consistent_many",
                side_effect=lambda references, query, kind, db_path=None: [
                    consistent for _ in references
                ],
            ),
        ):
            live_sessions.submit_observation(
                session["id"], first_path, db_path=self.db
            )
            before = self._persistence_state()
            with sqlite3.connect(self.db) as connection:
                connection.execute(
                    "CREATE TRIGGER fail_participant_support_update "
                    "BEFORE UPDATE OF support_count ON live_identity_participant "
                    f"WHEN OLD.session_id={session['id']} "
                    "BEGIN "
                    "SELECT RAISE(ABORT, 'injected participant update failure'); "
                    "END"
                )
            result = live_sessions.submit_observation(
                session["id"], second_path, db_path=self.db
            )

        self.assertEqual({}, result)
        self.assertEqual(before, self._persistence_state())

    def test_failed_profile_status_update_rolls_back_enrollment(self):
        session = live_sessions.create(db_path=self.db)
        first_path = self._audio("a-1.wav", 400, 0)
        second_path = self._audio("a-2.wav", 405, 0)

        with patch.object(identity.encoders, "encode", side_effect=self._encode):
            first = live_sessions.submit_observation(
                session["id"], first_path, db_path=self.db
            )
            profile_id = first["classification"]["participant"]["profile_id"]
            before = self._persistence_state()
            with sqlite3.connect(self.db) as connection:
                connection.execute(
                    "CREATE TRIGGER fail_profile_status_update "
                    "BEFORE UPDATE OF status ON profile "
                    f"WHEN OLD.id={profile_id} "
                    "BEGIN "
                    "SELECT RAISE(ABORT, 'injected profile status update failure'); "
                    "END"
                )
            result = identity.enroll(profile_id, second_path, db_path=self.db)

        self.assertEqual(
            {
                "status": "error",
                "reason": "injected profile status update failure",
            },
            result,
        )
        self.assertEqual(before, self._persistence_state())

    def test_failed_observation_insert_restores_pre_submit_state(self):
        session = live_sessions.create(db_path=self.db)
        first_path = self._audio("a-1.wav", 400, 0)
        second_path = self._audio("a-2.wav", 405, 0)
        consistent = {
            "consistent": True,
            "version": "pair-v1",
            "reasons": ["novelty_pair_consistent"],
        }

        with (
            patch.object(identity.encoders, "encode", side_effect=self._encode),
            patch.object(
                identity,
                "recordings_consistent_many",
                side_effect=lambda references, query, kind, db_path=None: [
                    consistent for _ in references
                ],
            ),
        ):
            live_sessions.submit_observation(
                session["id"], first_path, db_path=self.db
            )
            before = self._persistence_state()
            with sqlite3.connect(self.db) as connection:
                connection.execute(
                    "CREATE TRIGGER fail_second_observation "
                    "BEFORE INSERT ON live_identity_observation "
                    f"WHEN NEW.session_id={session['id']} AND NEW.sequence=2 "
                    "BEGIN "
                    "SELECT RAISE(ABORT, 'injected observation insert failure'); "
                    "END"
                )
            result = live_sessions.submit_observation(
                session["id"], second_path, db_path=self.db
            )

        self.assertEqual({}, result)
        self.assertEqual(before, self._persistence_state())

    def test_unique_pair_consistent_provisional_reinforces_before_pool_identification(self):
        session = live_sessions.create(db_path=self.db)
        a_first = self._audio("a-first.wav", 400, 0)
        a_second = self._audio("a-second.wav", 405, 0)
        b_first = self._audio("b-first.wav", 800, 1)
        b_second = self._audio("b-second.wav", 805, 1)

        with patch.object(identity.encoders, "encode", side_effect=self._encode):
            person_a = identity.create_profile(
                "Person A", identity.KIND_IMITATION, self.db
            )
            person_b = identity.create_profile(
                "Person B", identity.KIND_IMITATION, self.db
            )
            self.assertEqual(
                "enrolled",
                identity.enroll(person_a["id"], a_first, db_path=self.db)["status"],
            )
            self.assertEqual(
                "enrolled",
                identity.enroll(person_b["id"], b_first, db_path=self.db)["status"],
            )
            self.assertEqual(
                "enrolled",
                identity.enroll(person_b["id"], b_second, db_path=self.db)["status"],
            )

        created_at = "2026-07-30T00:00:00+00:00"
        with sqlite3.connect(self.db) as connection:
            connection.execute(
                "INSERT INTO live_identity_participant ("
                "session_id, profile_id, display_name, state, support_count, created_at"
                ") VALUES (?,?,?,?,?,?)",
                (
                    session["id"],
                    person_a["id"],
                    "Person A",
                    live_sessions.PARTICIPANT_PROVISIONAL,
                    1,
                    created_at,
                ),
            )
            connection.execute(
                "INSERT INTO live_identity_participant ("
                "session_id, profile_id, display_name, state, support_count, created_at, "
                "established_at"
                ") VALUES (?,?,?,?,?,?,?)",
                (
                    session["id"],
                    person_b["id"],
                    "Person B",
                    live_sessions.PARTICIPANT_ESTABLISHED,
                    2,
                    created_at,
                    created_at,
                ),
            )

        def pair(first, second, kind, db_path=None):
            consistent = (
                os.path.basename(first) == "a-first.wav"
                and os.path.basename(second) == "a-second.wav"
            )
            return {
                "consistent": consistent,
                "version": "pair-v1",
                "reasons": [
                    "novelty_pair_consistent"
                    if consistent
                    else "novelty_pair_inconsistent"
                ],
            }

        with (
            patch.object(identity.encoders, "encode", side_effect=self._encode),
            patch.object(
                identity,
                "recordings_consistent_many",
                side_effect=self._batch_pairs(pair),
            ),
            patch.object(
                identity,
                "identify_within_profiles",
                side_effect=AssertionError(
                    "generic identification must not run before unique provisional evidence"
                ),
            ) as identify,
        ):
            result = live_sessions.submit_observation(
                session["id"], a_second, db_path=self.db
            )

        self.assertEqual("participant", result["classification"]["status"])
        self.assertEqual(
            "Person A", result["classification"]["participant"]["display_name"]
        )
        self.assertEqual(
            live_sessions.PARTICIPANT_ESTABLISHED,
            result["classification"]["participant"]["state"],
        )
        self.assertEqual(2, result["classification"]["participant"]["support_count"])
        self.assertTrue(result["classification"]["reinforced"])
        identify.assert_not_called()

    def test_difficult_arrival_keeps_independent_pending_clusters_and_avoids_split(self):
        session = live_sessions.create(db_path=self.db)
        paths = {
            name: self._audio(f"{name}.wav", frequency, vector_index)
            for name, frequency, vector_index in (
                ("a-1", 400, 0),
                ("a-2", 405, 0),
                ("b-1", 800, 1),
                ("b-2", 805, 1),
                ("c-1", 1200, 2),
                ("c-2", 1205, 2),
                ("b-hard", 900, 3),
            )
        }

        def acoustic_group(path):
            name = os.path.basename(path)
            if name.startswith("a-"):
                return "a"
            if name in {"b-1.wav", "b-2.wav"}:
                return "b"
            if name.startswith("c-"):
                return "c"
            return "hard"

        def pair(first, second, kind, db_path=None):
            first_group = acoustic_group(first)
            second_group = acoustic_group(second)
            consistent = first_group == second_group and first_group != "hard"
            return {
                "consistent": consistent,
                "version": "pair-v1",
                "reasons": [
                    "novelty_pair_consistent"
                    if consistent
                    else "novelty_pair_inconsistent"
                ],
            }

        def identify(audio_path, profile_ids, kind, db_path=None, audit=True):
            profiles = [identity.get_profile(profile_id, self.db) for profile_id in profile_ids]
            if os.path.basename(audio_path) == "b-hard.wav":
                profiles.sort(key=lambda profile: profile["display_name"] != "Person B")
            return {
                "status": identity.STATUS_UNCERTAIN,
                "profile_id": None,
                "display_name": None,
                "band": "none",
                "reasons": ["below_accept_threshold", "new_or_unenrolled_source"],
                "kind": kind,
                "pool_size": len(profiles),
                "versions": {},
                "quality": {},
                "candidates": [
                    {
                        "profile_id": profile["id"],
                        "display_name": profile["display_name"],
                        "kind": profile["kind"],
                    }
                    for profile in profiles
                ],
            }

        with (
            patch.object(identity.encoders, "encode", side_effect=self._encode),
            patch.object(
                identity,
                "recordings_consistent_many",
                side_effect=self._batch_pairs(pair),
            ),
            patch.object(identity, "identify_within_profiles", side_effect=identify),
        ):
            results = {
                name: live_sessions.submit_observation(
                    session["id"], paths[name], db_path=self.db
                )
                for name in ("a-1", "b-1", "c-1", "a-2", "b-2", "c-2", "b-hard")
            }

        self.assertEqual("provisional_created", results["a-1"]["classification"]["status"])
        self.assertEqual("possible_new", results["b-1"]["classification"]["status"])
        self.assertEqual("possible_new", results["c-1"]["classification"]["status"])
        self.assertEqual("Person A", results["a-2"]["classification"]["participant"]["display_name"])
        self.assertEqual("Person B", results["b-2"]["classification"]["participant"]["display_name"])
        self.assertEqual("Person C", results["c-2"]["classification"]["participant"]["display_name"])
        self.assertEqual("leaning", results["b-hard"]["classification"]["status"])
        self.assertEqual(
            "Person B",
            results["b-hard"]["classification"]["participant"]["display_name"],
        )
        final = results["b-hard"]["session"]
        self.assertEqual(
            ["Person A", "Person B", "Person C"],
            [participant["display_name"] for participant in final["participants"]],
        )
        self.assertEqual(
            [2, 2, 2],
            [participant["support_count"] for participant in final["participants"]],
        )
        person_b = final["participants"][1]
        self.assertEqual(
            ["b-1.wav", "b-2.wav"],
            [
                os.path.basename(path)
                for path in identity.profile_reference_audio(
                    person_b["profile_id"], self.db
                )
            ],
        )

    def test_safe_outlier_with_two_established_profiles_stays_possible_new(self):
        session = live_sessions.create(db_path=self.db)
        a_first = self._audio("a-first.wav", 400, 0)
        a_second = self._audio("a-second.wav", 405, 0)
        b_first = self._audio("b-first.wav", 800, 1)
        b_second = self._audio("b-second.wav", 805, 1)
        c_first = self._audio("c-first.wav", 1200, 2)

        with patch.object(identity.encoders, "encode", side_effect=self._encode):
            profiles = []
            for display_name, references in (
                ("Person A", (a_first, a_second)),
                ("Person B", (b_first, b_second)),
            ):
                profile = identity.create_profile(
                    display_name,
                    identity.KIND_IMITATION,
                    self.db,
                )
                for reference in references:
                    self.assertEqual(
                        "enrolled",
                        identity.enroll(
                            profile["id"],
                            reference,
                            db_path=self.db,
                        )["status"],
                    )
                profiles.append(profile)

        created_at = "2026-07-30T00:00:00+00:00"
        with sqlite3.connect(self.db) as connection:
            for profile in profiles:
                connection.execute(
                    "INSERT INTO live_identity_participant ("
                    "session_id, profile_id, display_name, state, support_count, "
                    "created_at, established_at"
                    ") VALUES (?,?,?,?,?,?,?)",
                    (
                        session["id"],
                        profile["id"],
                        profile["display_name"],
                        live_sessions.PARTICIPANT_ESTABLISHED,
                        2,
                        created_at,
                        created_at,
                    ),
                )

        identified = {
            "status": identity.STATUS_UNCERTAIN,
            "profile_id": None,
            "display_name": None,
            "band": "none",
            "reasons": ["below_accept_threshold", "new_or_unenrolled_source"],
            "kind": identity.KIND_IMITATION,
            "pool_size": 2,
            "versions": {},
            "quality": {},
            "candidates": [
                {
                    "profile_id": profiles[0]["id"],
                    "display_name": "Person A",
                    "kind": identity.KIND_IMITATION,
                },
                {
                    "profile_id": profiles[1]["id"],
                    "display_name": "Person B",
                    "kind": identity.KIND_IMITATION,
                },
            ],
        }
        inconsistent = {
            "consistent": False,
            "version": "pair-v1",
            "reasons": ["novelty_pair_inconsistent"],
        }
        with (
            patch.object(
                identity,
                "identify_within_profiles",
                return_value=identified,
            ),
            patch.object(
                identity,
                "recordings_consistent_many",
                side_effect=lambda references, query, kind, db_path=None: [
                    inconsistent for _ in references
                ],
            ),
        ):
            result = live_sessions.submit_observation(
                session["id"], c_first, db_path=self.db
            )

        self.assertEqual("possible_new", result["classification"]["status"])
        self.assertIn(
            live_sessions.PENDING_NOVELTY_REASON,
            result["classification"]["reason_codes"],
        )
        self.assertEqual(2, len(result["session"]["participants"]))

    def test_weak_session_leader_is_leaning_and_never_enrolled(self):
        session = live_sessions.create(db_path=self.db)
        first_path = self._audio("a-1.wav", 400, 0)
        first_support = self._audio("a-2.wav", 405, 0)
        second_path = self._audio("b-1.wav", 800, 1)
        second_support = self._audio("b-2.wav", 805, 1)
        weak_path = self._audio("weak.wav", 410, 0)

        weak = {
            "status": "uncertain",
            "profile_id": None,
            "display_name": None,
            "band": "none",
            "reasons": ["close_top_profiles"],
            "kind": identity.KIND_IMITATION,
            "pool_size": 2,
            "versions": {},
            "quality": {},
            "candidates": [],
        }

        def pair(first, second, kind, db_path=None):
            first_prefix = os.path.basename(first).split("-", 1)[0]
            second_prefix = os.path.basename(second).split("-", 1)[0]
            consistent = (
                first_prefix == second_prefix
                and second_prefix in {"a", "b"}
            )
            return {
                "consistent": consistent,
                "version": "pair-v1",
                "reasons": [
                    "novelty_pair_consistent"
                    if consistent
                    else "novelty_pair_inconsistent"
                ],
            }

        with (
            patch.object(identity.encoders, "encode", side_effect=self._encode),
            patch.object(
                identity,
                "recordings_consistent_many",
                side_effect=self._batch_pairs(pair),
            ),
        ):
            first = live_sessions.submit_observation(
                session["id"], first_path, db_path=self.db
            )
            live_sessions.submit_observation(
                session["id"], first_support, db_path=self.db
            )
            live_sessions.submit_observation(
                session["id"], second_path, db_path=self.db
            )
            second = live_sessions.submit_observation(
                session["id"], second_support, db_path=self.db
            )
            weak["candidates"] = [
                {
                    "profile_id": first["classification"]["participant"]["profile_id"],
                    "display_name": "Person A",
                    "kind": identity.KIND_IMITATION,
                },
                {
                    "profile_id": second["classification"]["participant"]["profile_id"],
                    "display_name": "Person B",
                    "kind": identity.KIND_IMITATION,
                },
            ]
            with (
                patch.object(
                    identity,
                    "identify_within_profiles",
                    return_value=weak,
                ),
                patch.object(identity, "enroll", wraps=identity.enroll) as enroll,
            ):
                result = live_sessions.submit_observation(
                    session["id"], weak_path, db_path=self.db
                )
                duplicate = live_sessions.submit_observation(
                    session["id"], weak_path, db_path=self.db
                )

        self.assertEqual("leaning", result["classification"]["status"])
        self.assertEqual("Person A", result["classification"]["participant"]["display_name"])
        self.assertFalse(result["classification"]["reinforced"])
        self.assertEqual("duplicate", duplicate["classification"]["status"])
        self.assertIsNone(duplicate["observation"]["participant"])
        self.assertEqual(
            "Person A",
            duplicate["observation"]["closest_participant"]["display_name"],
        )
        self.assertFalse(duplicate["observation"]["reinforced"])
        enroll.assert_not_called()
        current = live_sessions.get(session["id"], self.db)
        self.assertEqual([2, 2], [p["support_count"] for p in current["participants"]])

    def test_exact_duplicate_is_stored_but_does_not_establish(self):
        session = live_sessions.create(db_path=self.db)
        path = self._audio("same.wav", 400, 0)

        with patch.object(identity.encoders, "encode", side_effect=self._encode):
            first = live_sessions.submit_observation(session["id"], path, db_path=self.db)
            with patch.object(identity, "enroll", wraps=identity.enroll) as enroll:
                duplicate = live_sessions.submit_observation(
                    session["id"], path, db_path=self.db
                )

        self.assertEqual("duplicate", duplicate["classification"]["status"])
        self.assertFalse(duplicate["classification"]["reinforced"])
        self.assertEqual(
            first["classification"]["participant"]["id"],
            duplicate["classification"]["participant"]["id"],
        )
        self.assertEqual(
            "provisional",
            duplicate["classification"]["participant"]["state"],
        )
        self.assertEqual(2, len(live_sessions.get(session["id"], self.db)["observations"]))
        enroll.assert_not_called()

    def test_invalid_audio_changes_no_participant_state(self):
        session = live_sessions.create(db_path=self.db)
        invalid_path = os.path.join(self._tmp.name, "invalid.wav")
        with open(invalid_path, "wb") as fh:
            fh.write(b"not a wav")

        first = live_sessions.submit_observation(
            session["id"], invalid_path, db_path=self.db
        )
        second = live_sessions.submit_observation(
            session["id"], invalid_path, db_path=self.db
        )

        self.assertEqual("invalid", first["classification"]["status"])
        self.assertEqual("invalid", second["classification"]["status"])
        current = live_sessions.get(session["id"], self.db)
        self.assertEqual([], current["participants"])
        self.assertEqual(["invalid", "invalid"], [
            observation["status"] for observation in current["observations"]
        ])

    def test_invalid_audio_cannot_split_an_existing_participant(self):
        session = live_sessions.create(db_path=self.db)
        first_path = self._audio("valid.wav", 400, 0)
        invalid_path = os.path.join(self._tmp.name, "later-invalid.wav")
        with open(invalid_path, "wb") as fh:
            fh.write(b"not a wav")

        with patch.object(identity.encoders, "encode", side_effect=self._encode):
            live_sessions.submit_observation(session["id"], first_path, db_path=self.db)
        result = live_sessions.submit_observation(
            session["id"], invalid_path, db_path=self.db
        )

        self.assertEqual("invalid", result["classification"]["status"])
        participants = live_sessions.get(session["id"], self.db)["participants"]
        self.assertEqual(["Person A"], [participant["display_name"] for participant in participants])
        self.assertEqual([1], [participant["support_count"] for participant in participants])

    def test_secondary_pair_encoder_failure_is_invalid_with_one_participant(self):
        session = live_sessions.create(db_path=self.db)
        first_path = self._audio("valid-first.wav", 400, 0)
        query_path = self._audio("valid-query.wav", 800, 1)

        with patch.object(identity.encoders, "encode", side_effect=self._encode):
            live_sessions.submit_observation(
                session["id"], first_path, db_path=self.db
            )

            identified = {
                "status": identity.STATUS_UNCERTAIN,
                "profile_id": None,
                "display_name": None,
                "band": "none",
                "reasons": [
                    "only_one_enrolled_profile",
                    "cannot_identify_without_a_comparison",
                    "enrol_a_second_profile_to_compare",
                ],
                "kind": identity.KIND_IMITATION,
                "pool_size": 1,
                "versions": {},
                "quality": {},
                "candidates": [],
            }
            unusable = {
                "consistent": False,
                "version": "pair-v1",
                "reasons": ["novelty_pair_audio_unusable"],
            }
            with (
                patch.object(
                    identity,
                    "recordings_consistent_many",
                    side_effect=lambda references, query, kind, db_path=None: [
                        unusable for _ in references
                    ],
                ),
                patch.object(
                    identity,
                    "identify_within_profiles",
                    return_value=identified,
                ),
            ):
                result = live_sessions.submit_observation(
                    session["id"], query_path, db_path=self.db
                )

        self.assertEqual("invalid", result["classification"]["status"])
        self.assertIn(
            "novelty_pair_audio_unusable",
            result["classification"]["reason_codes"],
        )
        current = live_sessions.get(session["id"], self.db)
        self.assertEqual(
            ["provisional_created", "invalid"],
            [observation["status"] for observation in current["observations"]],
        )
        self.assertEqual(
            [1],
            [
                participant["support_count"]
                for participant in current["participants"]
            ],
        )

    def test_labels_continue_past_person_z(self):
        session = live_sessions.create(db_path=self.db)
        paths = [
            self._audio(
                f"person-{index}-{take}.wav",
                200 + (index * 10) + take,
                index,
            )
            for index in range(27)
            for take in ((1,) if index == 0 else (1, 2))
        ]
        references = {}

        def enroll(profile_id, audio_path, **kwargs):
            references.setdefault(profile_id, []).append(audio_path)
            return {
                "status": "enrolled",
                "enrollments": len(references[profile_id]),
                "profile_status": "provisional",
            }

        def identify(audio_path, profile_ids, kind, db_path=None, audit=True):
            return {
                "status": "uncertain",
                "profile_id": None,
                "display_name": None,
                "band": "none",
                "reasons": ["below_accept_threshold", "new_or_unenrolled_source"],
                "kind": kind,
                "pool_size": len(profile_ids),
                "versions": {},
                "quality": {},
                "candidates": [],
            }

        def pair(first, second, kind, db_path=None):
            first_group = "-".join(os.path.basename(first).split("-")[:2])
            second_group = "-".join(os.path.basename(second).split("-")[:2])
            consistent = first_group == second_group
            return {
                "consistent": consistent,
                "version": "pair-v1",
                "reasons": [
                    "novelty_pair_consistent"
                    if consistent
                    else "novelty_pair_inconsistent"
                ],
            }

        with (
            patch.object(identity, "enroll", side_effect=enroll),
            patch.object(
                identity,
                "profile_reference_audio",
                side_effect=lambda profile_id, db_path=None: references.get(profile_id, []),
            ),
            patch.object(
                identity,
                "recordings_consistent_many",
                side_effect=self._batch_pairs(pair),
            ),
            patch.object(identity, "identify_within_profiles", side_effect=identify),
        ):
            results = [
                live_sessions.submit_observation(session["id"], path, db_path=self.db)
                for path in paths
            ]

        self.assertIsNotNone(
            results[-1]["classification"]["participant"],
            [
                result["classification"]["status"]
                for result in results
            ],
        )
        self.assertEqual(
            "Person AA",
            results[-1]["classification"]["participant"]["display_name"],
        )

    def test_completed_session_rejects_later_observations(self):
        session = live_sessions.create(db_path=self.db)
        completed = live_sessions.complete(session["id"], self.db)
        path = self._audio("late.wav", 400, 0)

        result = live_sessions.submit_observation(session["id"], path, db_path=self.db)

        self.assertEqual("completed", completed["status"])
        self.assertEqual("session_completed", result["classification"]["status"])
        self.assertEqual([], live_sessions.get(session["id"], self.db)["observations"])

    def test_second_session_preserves_infant_profiles_and_first_session(self):
        infant = identity.create_profile("Baby", identity.KIND_INFANT, self.db)
        first_session = live_sessions.create(db_path=self.db)
        path = self._audio("visitor.wav", 400, 0)

        with patch.object(identity.encoders, "encode", side_effect=self._encode):
            live_sessions.submit_observation(first_session["id"], path, db_path=self.db)
        second_session = live_sessions.create(db_path=self.db)

        self.assertNotEqual(first_session["id"], second_session["id"])
        self.assertEqual(1, len(live_sessions.get(first_session["id"], self.db)["participants"]))
        self.assertEqual(0, len(live_sessions.get(second_session["id"], self.db)["participants"]))
        self.assertEqual(
            identity.KIND_INFANT,
            identity.get_profile(infant["id"], self.db)["kind"],
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
