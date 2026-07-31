import tempfile
import unittest
from pathlib import Path

from src import identity, profile_views, store


class ProfileViewTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.database = str(Path(self.temporary.name) / "episodes.db")
        store.init_db(self.database)
        self.profile = identity.create_profile(
            "Demo Baby",
            kind=identity.KIND_INFANT,
            db_path=self.database,
        )

    def tearDown(self):
        self.temporary.cleanup()

    def _episode(self, minute, **overrides):
        episode = {
            "subject_id": f"profile-{self.profile['id']}",
            "started_at": f"2026-07-30T12:{minute:02d}:00+00:00",
            "duration_s": 18.5,
            "audio_path": f"/managed/episode-{minute}.wav",
            "fingerprint": [float(minute or 1)] * 87,
            "transcript": "I picked her up and held her upright.",
            "interventions": [
                {
                    "action": "held baby upright",
                    "evidence": "held her upright",
                    "worked": True,
                }
            ],
            "outcome": "She settled after two minutes.",
            "outcome_src": "caregiver",
            "worked": True,
            "context": {
                "hour_local": 12,
                "tags": ["afternoon", "after feeding"],
            },
        }
        episode.update(overrides)
        return store.save_episode(episode, self.database)

    def test_summary_counts_memories_and_reports_latest_activity(self):
        self._episode(5)
        self._episode(15)
        result = profile_views.summary(self.profile["id"], self.database)
        self.assertEqual("ready", result["status"])
        self.assertEqual("Demo Baby", result["profile"]["display_name"])
        self.assertEqual(2, result["profile"]["memory_count"])
        self.assertEqual(
            "2026-07-30T12:15:00+00:00",
            result["profile"]["latest_memory_at"],
        )
        self.assertIn("acoustic_pattern", result["profile"]["available_context"])
        self.assertIn("time_of_day", result["profile"]["available_context"])
        self.assertIn("caregiver_tags", result["profile"]["available_context"])

    def test_incidents_are_paginated_and_path_free(self):
        ids = [self._episode(minute) for minute in (5, 15, 25)]
        result = profile_views.incidents(
            self.profile["id"],
            self.database,
            limit=2,
        )
        self.assertEqual("ready", result["status"])
        self.assertEqual([ids[2], ids[1]], [item["id"] for item in result["incidents"]])
        self.assertEqual(ids[1], result["next_before_id"])
        rendered = repr(result)
        self.assertNotIn("audio_path", rendered)
        self.assertNotIn("fingerprint", rendered)
        self.assertEqual(
            f"/api/profiles/{self.profile['id']}/incidents/{ids[2]}/audio",
            result["incidents"][0]["audio_url"],
        )

        next_page = profile_views.incidents(
            self.profile["id"],
            self.database,
            limit=2,
            before_id=ids[1],
        )
        self.assertEqual([ids[0]], [item["id"] for item in next_page["incidents"]])
        self.assertIsNone(next_page["next_before_id"])

    def test_detail_surfaces_transcript_context_action_and_outcome(self):
        incident_id = self._episode(5)
        result = profile_views.incident(
            self.profile["id"],
            incident_id,
            self.database,
        )
        self.assertEqual("ready", result["status"])
        incident = result["incident"]
        self.assertEqual(
            "I picked her up and held her upright.",
            incident["transcript"],
        )
        self.assertEqual(["afternoon", "after feeding"], incident["tags"])
        self.assertEqual("held baby upright", incident["interventions"][0]["action"])
        self.assertEqual("She settled after two minutes.", incident["outcome"])
        self.assertTrue(incident["worked"])
        self.assertEqual(12, incident["time"]["hour_local"])

    def test_detail_labels_only_explicit_transcript_sources(self):
        incident_id = self._episode(
            6,
            transcript=(
                "Audio transcript: I picked her up. "
                "Typed caregiver follow-up: She calmed after two minutes."
            ),
        )
        incident = profile_views.incident(
            self.profile["id"],
            incident_id,
            self.database,
        )["incident"]
        self.assertEqual(
            [
                {
                    "text": "I picked her up.",
                    "source": "captured_transcript",
                    "label": "Captured transcript",
                },
                {
                    "text": "She calmed after two minutes.",
                    "source": "typed_follow_up",
                    "label": "Caregiver typed",
                },
            ],
            incident["speech"]["segments"],
        )

        unmarked_id = self._episode(7, transcript="A stored note without a source marker.")
        unmarked = profile_views.incident(
            self.profile["id"],
            unmarked_id,
            self.database,
        )["incident"]
        self.assertEqual("caregiver_record", unmarked["speech"]["segments"][0]["source"])
        self.assertEqual("Caregiver record", unmarked["speech"]["segments"][0]["label"])

    def test_other_profile_and_missing_incident_are_not_found(self):
        incident_id = self._episode(5)
        other = identity.create_profile(
            "Other Baby",
            kind=identity.KIND_INFANT,
            db_path=self.database,
        )
        self.assertEqual(
            "profile_not_found",
            profile_views.summary(999, self.database)["reason"],
        )
        self.assertEqual(
            "incident_not_found",
            profile_views.incident(other["id"], incident_id, self.database)["reason"],
        )


if __name__ == "__main__":
    unittest.main()
