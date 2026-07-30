import unittest
from unittest.mock import patch


class CurrentContextTests(unittest.TestCase):
    def test_build_current_context_combines_time_events_and_deduplicated_explicit_tags(self):
        from src import context

        events = [
            {
                "id": 12,
                "profile_id": 7,
                "event_type": "feeding",
                "occurred_at": "2026-07-29T13:30:00-04:00",
                "details": {},
            },
            {
                "id": 11,
                "profile_id": 7,
                "event_type": "sleep",
                "occurred_at": "2026-07-29T12:00:00-04:00",
                "details": {"phase": "end"},
            },
            {
                "id": 10,
                "profile_id": 7,
                "event_type": "diaper",
                "occurred_at": "2026-07-29T13:00:00-04:00",
                "details": {},
            },
        ]
        with patch.object(
            context.store,
            "list_care_events",
            return_value=events,
            create=True,
        ):
            result = context.build_current_context(
                7,
                now="2026-07-29T14:00:00-04:00",
                tags=["Teething", " teething ", "Overtired"],
                db_path="/tmp/isolated.db",
            )

        self.assertEqual(14, result["hour_local"])
        self.assertEqual(
            [
                "teething",
                "overtired",
                "last_feed_under_2h",
                "awake_2_to_4h",
                "recent_diaper",
            ],
            result["tags"],
        )
        self.assertEqual([12, 11, 10], result["care_event_ids"])

    def test_build_current_context_uses_only_events_returned_for_the_requested_profile(self):
        from src import context

        seen = []

        def profile_events(profile_id, since=None, path=None):
            seen.append((profile_id, path))
            return [
                {
                    "id": 22,
                    "profile_id": profile_id,
                    "event_type": "feeding",
                    "occurred_at": "2026-07-29T09:00:00-04:00",
                    "details": {},
                }
            ]

        with patch.object(
            context.store,
            "list_care_events",
            side_effect=profile_events,
            create=True,
        ):
            result = context.build_current_context(
                9,
                now="2026-07-29T14:00:00-04:00",
                db_path="/tmp/profile-nine.db",
            )

        self.assertEqual([(9, "/tmp/profile-nine.db")], seen)
        self.assertEqual(["last_feed_over_4h"], result["tags"])
        self.assertEqual([22], result["care_event_ids"])

    def test_build_current_context_rejects_naive_time_instead_of_guessing_a_timezone(self):
        from src import context

        result = context.build_current_context(
            7,
            now="2026-07-29T14:00:00",
        )

        self.assertEqual({}, result)


if __name__ == "__main__":
    unittest.main()
