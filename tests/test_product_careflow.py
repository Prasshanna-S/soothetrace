import os
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


if __name__ == "__main__":
    unittest.main()
