import os
import threading
import unittest
from tempfile import TemporaryDirectory
from unittest.mock import patch


def _episode(subject_id, started_at, action, outcome):
    return {
        "subject_id": subject_id,
        "started_at": started_at,
        "duration_s": 12.0,
        "audio_path": "",
        "fingerprint": [0.25] * 87,
        "transcript": f"I {action}.",
        "interventions": [
            {
                "order": 1,
                "action": action,
                "evidence": action,
            }
        ],
        "outcome": outcome,
        "outcome_src": "caregiver",
        "worked": True,
        "context": {"hour_local": 3, "tags": ["last_feed_under_2h"]},
    }


class CareFlowTests(unittest.TestCase):
    def test_completed_attempt_conflicts_even_after_its_capture_is_removed(self):
        from src import careflow, identity

        with TemporaryDirectory() as directory:
            db_path = os.path.join(directory, "episodes.db")
            canonical = os.path.join(directory, "canonical.wav")
            with open(canonical, "wb") as audio:
                audio.write(b"RIFF-test-wave")
            profile = identity.create_profile("Baby A", db_path=db_path)
            attempt = {
                "id": 38,
                "status": "match",
                "matched_profile_id": profile["id"],
                "captures": [{"canonical_audio_path": canonical}],
            }
            with (
                patch.object(
                    careflow.identity,
                    "get_identity_attempt",
                    return_value=attempt,
                    create=True,
                ),
                patch.object(
                    careflow.fingerprint,
                    "compute_windowed",
                    return_value=[0.3] * 87,
                ),
                patch.object(
                    careflow.session.fingerprint,
                    "compute_windowed",
                    return_value=[0.3] * 87,
                ),
                patch.object(
                    careflow.session.fingerprint,
                    "duration_s",
                    return_value=8.0,
                ),
                patch.object(careflow.session.speech, "transcribe", return_value=""),
                patch.object(
                    careflow.session.speech,
                    "extract_interventions",
                    return_value=[],
                ),
                patch.object(
                    careflow.session.speech,
                    "infer_outcome",
                    return_value=None,
                ),
            ):
                first = careflow.complete_incident(
                    38,
                    "Rocking worked.",
                    db_path=db_path,
                )
                os.remove(canonical)
                second = careflow.complete_incident(
                    38,
                    "Rocking worked.",
                    db_path=db_path,
                )

        self.assertEqual("complete", first["status"])
        self.assertEqual(
            {"status": "conflict", "reason": "incident_already_completed"},
            second,
        )

    def test_simultaneous_completion_requests_save_exactly_one_episode(self):
        from src import careflow, identity, store

        with TemporaryDirectory() as directory:
            db_path = os.path.join(directory, "episodes.db")
            canonical = os.path.join(directory, "canonical.wav")
            with open(canonical, "wb") as audio:
                audio.write(b"RIFF-test-wave")
            profile = identity.create_profile("Baby A", db_path=db_path)
            subject_id = f"profile-{profile['id']}"
            attempt = {
                "id": 37,
                "status": "match",
                "matched_profile_id": profile["id"],
                "captures": [{"canonical_audio_path": canonical}],
            }
            rendezvous = threading.Barrier(2)
            real_completed = careflow._attempt_already_completed
            completion_checks = 0
            completion_checks_lock = threading.Lock()

            def synchronized_completion_check(*args, **kwargs):
                nonlocal completion_checks
                result = real_completed(*args, **kwargs)
                with completion_checks_lock:
                    completion_checks += 1
                    current_check = completion_checks
                if current_check <= 2:
                    rendezvous.wait(timeout=3)
                return result

            results = []
            with (
                patch.object(
                    careflow.identity,
                    "get_identity_attempt",
                    return_value=attempt,
                    create=True,
                ),
                patch.object(
                    careflow.fingerprint,
                    "compute_windowed",
                    return_value=[0.3] * 87,
                ),
                patch.object(
                    careflow.session.fingerprint,
                    "compute_windowed",
                    return_value=[0.3] * 87,
                ),
                patch.object(
                    careflow.session.fingerprint,
                    "duration_s",
                    return_value=8.0,
                ),
                patch.object(careflow.session.speech, "transcribe", return_value=""),
                patch.object(
                    careflow.session.speech,
                    "extract_interventions",
                    return_value=[],
                ),
                patch.object(
                    careflow.session.speech,
                    "infer_outcome",
                    return_value=None,
                ),
                patch.object(
                    careflow,
                    "_attempt_already_completed",
                    side_effect=synchronized_completion_check,
                ),
            ):
                threads = [
                    threading.Thread(
                        target=lambda: results.append(
                            careflow.complete_incident(
                                37,
                                "Rocking worked.",
                                db_path=db_path,
                            )
                        )
                    )
                    for _ in range(2)
                ]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join(timeout=5)
            rows = store.list_episodes(subject_id, db_path)

        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(1, len(rows))
        self.assertEqual(
            ["complete", "conflict"],
            sorted(result["status"] for result in results),
        )

    def test_completing_the_same_identity_attempt_twice_saves_one_episode(self):
        from src import careflow, identity, store

        with TemporaryDirectory() as directory:
            db_path = os.path.join(directory, "episodes.db")
            canonical = os.path.join(directory, "canonical.wav")
            with open(canonical, "wb") as audio:
                audio.write(b"RIFF-test-wave")
            profile = identity.create_profile("Baby A", db_path=db_path)
            subject_id = f"profile-{profile['id']}"
            attempt = {
                "id": 39,
                "status": "match",
                "matched_profile_id": profile["id"],
                "captures": [{"canonical_audio_path": canonical}],
            }
            with (
                patch.object(
                    careflow.identity,
                    "get_identity_attempt",
                    return_value=attempt,
                    create=True,
                ),
                patch.object(
                    careflow.fingerprint,
                    "compute_windowed",
                    return_value=[0.3] * 87,
                ),
                patch.object(
                    careflow.session.fingerprint,
                    "compute_windowed",
                    return_value=[0.3] * 87,
                ),
                patch.object(
                    careflow.session.fingerprint,
                    "duration_s",
                    return_value=8.0,
                ),
                patch.object(careflow.session.speech, "transcribe", return_value=""),
                patch.object(
                    careflow.session.speech,
                    "extract_interventions",
                    return_value=[],
                ),
                patch.object(
                    careflow.session.speech,
                    "infer_outcome",
                    return_value=None,
                ),
            ):
                first = careflow.complete_incident(
                    39,
                    "Rocking worked.",
                    db_path=db_path,
                )
                second = careflow.complete_incident(
                    39,
                    "Rocking worked.",
                    db_path=db_path,
                )
            rows = store.list_episodes(subject_id, db_path)

        self.assertEqual("complete", first["status"])
        self.assertEqual(
            {"status": "conflict", "reason": "incident_already_completed"},
            second,
        )
        self.assertEqual(1, len(rows))

    def test_preview_reads_history_without_saving_the_current_incident(self):
        from src import careflow, identity, store

        with TemporaryDirectory() as directory:
            db_path = os.path.join(directory, "episodes.db")
            canonical = os.path.join(directory, "canonical.wav")
            with open(canonical, "wb") as audio:
                audio.write(b"RIFF-test-wave")

            profile = identity.create_profile("Baby A", db_path=db_path)
            subject_id = f"profile-{profile['id']}"
            store.save_episode(
                _episode(
                    subject_id,
                    "2026-07-20T03:00:00-04:00",
                    "walked around the room",
                    "The caregiver said the baby settled.",
                ),
                db_path,
            )
            before = store.list_episodes(subject_id, db_path)
            attempt = {
                "id": 40,
                "status": "match",
                "matched_profile_id": profile["id"],
                "captures": [{"canonical_audio_path": canonical}],
            }
            with (
                patch.object(
                    careflow.identity,
                    "get_identity_attempt",
                    return_value=attempt,
                    create=True,
                ),
                patch.object(
                    careflow.fingerprint,
                    "compute_windowed",
                    return_value=[0.3] * 87,
                ),
            ):
                result = careflow.preview_incident(
                    40,
                    explicit_tags=["Evening"],
                    db_path=db_path,
                )
            after = store.list_episodes(subject_id, db_path)

        self.assertEqual("preview", result["status"])
        self.assertEqual("Baby A", result["identity"]["display_name"])
        self.assertEqual(len(before), len(after))
        self.assertNotIn("episode", result)

    def test_unmatched_attempt_cannot_read_history_or_save_an_episode(self):
        from src import careflow, store

        with TemporaryDirectory() as directory:
            db_path = os.path.join(directory, "episodes.db")
            with patch.object(
                careflow.identity,
                "get_identity_attempt",
                return_value={
                    "id": 41,
                    "status": "pending",
                    "resolved_profile_id": None,
                    "captures": [],
                },
                create=True,
            ):
                result = careflow.complete_incident(
                    41,
                    "Rocking worked.",
                    db_path=db_path,
                )

            rows = store.list_episodes("profile-7", db_path)

        self.assertEqual(
            {"status": "blocked", "reason": "identity_not_matched"},
            result,
        )
        self.assertEqual([], rows)

    def test_matched_attempt_reads_only_that_profile_before_saving_current_incident(self):
        from src import careflow, identity, store

        with TemporaryDirectory() as directory:
            db_path = os.path.join(directory, "episodes.db")
            canonical = os.path.join(directory, "canonical.wav")
            with open(canonical, "wb") as audio:
                audio.write(b"RIFF-test-wave")

            profile_a = identity.create_profile("Baby A", db_path=db_path)
            profile_b = identity.create_profile("Baby B", db_path=db_path)
            subject_a = f"profile-{profile_a['id']}"
            subject_b = f"profile-{profile_b['id']}"
            for index in range(6):
                store.save_episode(
                    _episode(
                        subject_a,
                        f"2026-07-{20 + index:02d}T03:00:00-04:00",
                        "walked around the room",
                        "The caregiver said the baby settled.",
                    ),
                    db_path,
                )
                store.save_episode(
                    _episode(
                        subject_b,
                        f"2026-07-{20 + index:02d}T15:00:00-04:00",
                        "used a hair dryer",
                        "A different profile settled.",
                    ),
                    db_path,
                )

            count_seen_during_retrieval = []

            def profile_scenarios(subject_id, fingerprint_vec, current_context, k, db_path):
                rows = store.list_episodes(subject_id, db_path)
                count_seen_during_retrieval.append(len(rows))
                return [
                    {
                        "episode_id": row["id"],
                        "band": "weak",
                        "started_at": row["started_at"],
                        "interventions": row["interventions"],
                        "outcome": row["outcome"],
                        "outcome_src": row["outcome_src"],
                        "worked": row["worked"],
                        "components": {"time_of_day": 1.0, "notes": 1.0},
                    }
                    for row in rows[:3]
                ]

            attempt = {
                "id": 42,
                "status": "match",
                "matched_profile_id": profile_a["id"],
                "captures": [
                    {
                        "id": 90,
                        "canonical_audio_path": canonical,
                        "identity_audio_path": os.path.join(directory, "identity.wav"),
                    }
                ],
            }
            with (
                patch.object(
                    careflow.identity,
                    "get_identity_attempt",
                    return_value=attempt,
                    create=True,
                ),
                patch.object(
                    careflow.retrieve,
                    "find_scenarios",
                    side_effect=profile_scenarios,
                ),
                patch.object(
                    careflow.fingerprint,
                    "compute_windowed",
                    return_value=[0.3] * 87,
                ),
                patch.object(
                    careflow.session.fingerprint,
                    "compute_windowed",
                    return_value=[0.3] * 87,
                ),
                patch.object(
                    careflow.session.fingerprint,
                    "duration_s",
                    return_value=8.0,
                ),
                patch.object(
                    careflow.session.speech,
                    "transcribe",
                    return_value="I picked the baby up and walked around the room.",
                ),
                patch.object(
                    careflow.session.speech,
                    "extract_interventions",
                    return_value=[
                        {
                            "order": 1,
                            "action": "walked around the room",
                            "evidence": "walked around the room",
                        }
                    ],
                ),
            ):
                result = careflow.complete_incident(
                    42,
                    "Walking worked and the baby settled.",
                    explicit_tags=["Teething"],
                    db_path=db_path,
                )

            saved_a = store.list_episodes(subject_a, db_path)
            saved_b = store.list_episodes(subject_b, db_path)

        self.assertEqual("complete", result["status"])
        self.assertEqual("Baby A", result["identity"]["display_name"])
        self.assertEqual([6], count_seen_during_retrieval)
        self.assertEqual(7, len(saved_a))
        self.assertEqual(6, len(saved_b))
        self.assertEqual(subject_a, result["episode"]["subject_id"])
        self.assertEqual(42, result["episode"]["context"]["identity_attempt_id"])
        self.assertEqual(profile_a["id"], result["episode"]["context"]["profile_id"])
        self.assertIn("teething", result["episode"]["context"]["tags"])
        self.assertEqual("grounded", result["guidance"]["status"])
        self.assertEqual("walked around the room", result["guidance"]["action"])
        self.assertNotIn("hair dryer", str(result).casefold())

    def test_missing_managed_capture_returns_a_structured_failure(self):
        from src import careflow

        attempt = {
            "id": 43,
            "status": "match",
            "matched_profile_id": 7,
            "captures": [{"id": 91, "canonical_audio_path": "/missing/capture.wav"}],
        }
        with (
            patch.object(
                careflow.identity,
                "get_identity_attempt",
                return_value=attempt,
                create=True,
            ),
            patch.object(
                careflow.identity,
                "get_profile",
                return_value={
                    "id": 7,
                    "display_name": "Baby A",
                    "kind": "infant",
                },
            ),
        ):
            result = careflow.complete_incident(43, None)

        self.assertEqual(
            {"status": "error", "reason": "managed_capture_unavailable"},
            result,
        )


class ProfilePreviewTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.directory = self.tempdir.name
        self.db_path = os.path.join(self.directory, "episodes.db")
        self.canonical = os.path.join(self.directory, "canonical.wav")
        with open(self.canonical, "wb") as audio:
            audio.write(b"RIFF-test-wave")

    def test_profile_preview_reads_only_selected_profile_at_supplied_time(self):
        from src import careflow, identity, store

        selected = identity.create_profile("Baby A", db_path=self.db_path)
        other = identity.create_profile("Baby B", db_path=self.db_path)
        selected_subject = f"profile-{selected['id']}"
        other_subject = f"profile-{other['id']}"
        store.save_episode(
            _episode(
                selected_subject,
                "2026-07-20T03:00:00-04:00",
                "held baby upright",
                "The caregiver said the baby settled.",
            ),
            self.db_path,
        )
        store.save_episode(
            _episode(
                other_subject,
                "2026-07-20T15:00:00-04:00",
                "used a hair dryer",
                "A different profile settled.",
            ),
            self.db_path,
        )
        before_selected = store.list_episodes(selected_subject, self.db_path)
        before_other = store.list_episodes(other_subject, self.db_path)
        scenario = {
            "episode_id": before_selected[0]["id"],
            "started_at": before_selected[0]["started_at"],
            "interventions": before_selected[0]["interventions"],
            "outcome": before_selected[0]["outcome"],
            "outcome_src": "caregiver",
            "worked": True,
            "contributions": ["cry pattern"],
            "audio_url": f"/api/audio/episodes/{before_selected[0]['id']}",
        }
        grounded = {
            "status": "grounded",
            "recommendation": "Held baby upright.",
            "incident_ids": [before_selected[0]["id"]],
        }

        with (
            patch.object(
                careflow.identity,
                "get_identity_attempt",
                side_effect=AssertionError("profile preview must not read identity attempts"),
                create=True,
            ),
            patch.object(
                careflow.fingerprint,
                "compute_windowed",
                return_value=[0.3] * 87,
            ),
            patch.object(
                careflow.context,
                "build_current_context",
                return_value={
                    "hour_local": 3,
                    "tags": ["evening"],
                    "care_event_ids": [],
                },
            ) as build_context,
            patch.object(
                careflow.retrieve,
                "find_scenarios",
                return_value=[scenario],
            ) as find_scenarios,
            patch.object(
                careflow.retrieve,
                "episode_count",
                return_value=1,
            ) as episode_count,
            patch.object(
                careflow.retrieve,
                "intervention_tally",
                return_value=[],
            ) as intervention_tally,
            patch.object(
                careflow.guidance,
                "build_guidance",
                return_value=grounded,
            ),
        ):
            result = careflow.preview_profile_incident(
                selected["id"],
                self.canonical,
                explicit_tags=["Evening"],
                now="2026-07-30T03:15:00-04:00",
                db_path=self.db_path,
            )

        self.assertEqual("preview", result["status"])
        self.assertEqual(
            {
                "profile_id": selected["id"],
                "display_name": "Baby A",
                "kind": "infant",
            },
            result["identity"],
        )
        self.assertEqual([scenario], result["scenarios"])
        self.assertEqual(grounded, result["guidance"])
        self.assertEqual(self.canonical, result["_canonical_audio"])
        self.assertEqual(3, result["_current_context"]["hour_local"])
        build_context.assert_called_once_with(
            selected["id"],
            now="2026-07-30T03:15:00-04:00",
            tags=["Evening"],
            db_path=self.db_path,
        )
        find_scenarios.assert_called_once_with(
            selected_subject,
            [0.3] * 87,
            result["_current_context"],
            k=3,
            db_path=self.db_path,
        )
        episode_count.assert_called_once_with(selected_subject, self.db_path)
        intervention_tally.assert_called_once_with(selected_subject, self.db_path)
        self.assertEqual(
            before_selected,
            store.list_episodes(selected_subject, self.db_path),
        )
        self.assertEqual(
            before_other,
            store.list_episodes(other_subject, self.db_path),
        )

    def test_profile_preview_rejects_absent_or_non_infant_profiles_before_history(self):
        from src import careflow, identity

        non_infant = identity.create_profile(
            "Adult",
            identity.KIND_IMITATION,
            self.db_path,
        )
        with (
            patch.object(careflow.retrieve, "find_scenarios") as find_scenarios,
            patch.object(careflow.guidance, "build_guidance") as build_guidance,
        ):
            absent = careflow.preview_profile_incident(
                999999,
                self.canonical,
                db_path=self.db_path,
            )
            wrong_kind = careflow.preview_profile_incident(
                non_infant["id"],
                self.canonical,
                db_path=self.db_path,
            )

        self.assertEqual("error", absent["status"])
        self.assertEqual("error", wrong_kind["status"])
        find_scenarios.assert_not_called()
        build_guidance.assert_not_called()

    def test_profile_preview_rejects_missing_or_unusable_audio_before_history(self):
        from src import careflow, identity

        profile = identity.create_profile("Baby A", db_path=self.db_path)
        with (
            patch.object(
                careflow.fingerprint,
                "compute_windowed",
                return_value=None,
            ),
            patch.object(careflow.retrieve, "find_scenarios") as find_scenarios,
        ):
            missing = careflow.preview_profile_incident(
                profile["id"],
                os.path.join(self.directory, "missing.wav"),
                db_path=self.db_path,
            )
            unusable = careflow.preview_profile_incident(
                profile["id"],
                self.canonical,
                db_path=self.db_path,
            )

        self.assertEqual(
            {"status": "error", "reason": "managed_capture_unavailable"},
            missing,
        )
        self.assertEqual(
            {"status": "error", "reason": "capture_has_no_identity_signal"},
            unusable,
        )
        find_scenarios.assert_not_called()


if __name__ == "__main__":
    unittest.main()
