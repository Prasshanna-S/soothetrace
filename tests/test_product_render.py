import unittest


class RecallCardTests(unittest.TestCase):
    def test_recall_card_keeps_a_specific_time_with_windows_strftime_rules(self):
        from datetime import datetime as real_datetime
        from unittest.mock import patch

        from src import render

        class WindowsLikeValue:
            def __init__(self, value):
                self.value = value
                self.day = value.day
                self.hour = value.hour

            def strftime(self, template):
                if "%-" in template:
                    raise ValueError("Invalid format string")
                return self.value.strftime(template)

        class WindowsLikeDateTime:
            @classmethod
            def fromisoformat(cls, value):
                return WindowsLikeValue(real_datetime.fromisoformat(value))

        with patch.object(render, "datetime", WindowsLikeDateTime):
            text = render.recall_card(
                [
                    {
                        "episode_id": 2,
                        "similarity": 0.9,
                        "band": "strong",
                        "started_at": "2026-07-20T03:00:00-04:00",
                        "interventions": [],
                        "outcome": None,
                    }
                ],
                episode_count=4,
            )

        self.assertIn("Mon Jul 20 at 3:00 AM", text)
        self.assertNotIn("an earlier recording", text)

    def test_recall_card_shows_band_but_never_similarity_number(self):
        try:
            from src import render
        except ImportError:
            self.fail("src.render must own human-facing recall formatting")

        text = render.recall_card(
            [
                {
                    "episode_id": 2,
                    "similarity": 0.9432,
                    "band": "strong",
                    "started_at": "2026-07-20T03:00:00-04:00",
                    "interventions": [
                        {
                            "order": 1,
                            "action": "offered bottle",
                            "evidence": "offered a bottle",
                        }
                    ],
                    "outcome": "fed him",
                    "outcome_src": "caregiver",
                }
            ],
            episode_count=4,
        )

        self.assertIn("strong", text.casefold())
        self.assertIn("offered bottle", text)
        self.assertIn("fed him", text)
        self.assertNotIn("0.9432", text)
        self.assertNotIn("94.32", text)
        self.assertNotIn("%", text)

    def test_recall_card_is_honest_when_history_is_too_small(self):
        from src import render

        text = render.recall_card([], episode_count=2)

        self.assertIn("only your 2nd recording", text.casefold())
        self.assertIn("not enough to compare yet", text.casefold())

    def test_recall_card_has_a_real_zero_history_empty_state(self):
        from src import render

        text = render.recall_card([], episode_count=0)

        self.assertIn("no recordings yet", text.casefold())
        self.assertNotIn("0th", text.casefold())

    def test_recall_card_labels_inferred_and_synthetic_outcomes(self):
        from src import render

        base_match = {
            "episode_id": 2,
            "similarity": 0.8,
            "band": "strong",
            "started_at": "2026-07-20T03:00:00-04:00",
            "interventions": [],
            "outcome": "she settled",
        }

        inferred = render.recall_card(
            [{**base_match, "outcome_src": "inferred"}],
            episode_count=4,
        )
        synthetic = render.recall_card(
            [{**base_match, "outcome_src": "seed"}],
            episode_count=4,
        )

        self.assertIn("inferred from transcript", inferred.casefold())
        self.assertIn("synthetic demo data", synthetic.casefold())


class SafetyGuidanceTests(unittest.TestCase):
    def test_repeated_unknown_outcomes_trigger_step_away_guidance(self):
        from src import render

        self.assertTrue(
            hasattr(render, "caregiver_guidance"),
            "render.caregiver_guidance must implement the required safety message",
        )
        episodes = [
            {"duration_s": 120, "worked": None},
            {"duration_s": 180, "worked": None},
            {"duration_s": 90, "worked": None},
        ]

        text = render.caregiver_guidance(episodes)

        self.assertIn("safe place", text.casefold())
        self.assertIn("step away", text.casefold())
        self.assertIn("consider talking to your pediatrician", text.casefold())
        self.assertNotIn("diagnos", text.casefold())
        self.assertNotIn("colic", text.casefold())
        self.assertNotIn("failed", text.casefold())

    def test_old_long_episode_does_not_make_guidance_permanent(self):
        from src import render

        episodes_newest_first = [
            {"duration_s": 120, "worked": True},
            {"duration_s": 90, "worked": True},
            {"duration_s": 900, "worked": False},
        ]

        text = render.caregiver_guidance(episodes_newest_first)

        self.assertEqual(text, "")


class GroundedGuidanceCardTests(unittest.TestCase):
    def test_guidance_card_shows_provenance_without_debug_scores(self):
        from src import render

        text = render.guidance_card(
            {
                "status": "grounded",
                "headline": "What helped before",
                "action": "walked",
                "support_count": 2,
                "incident_ids": [11, 7],
                "outcomes": [
                    {
                        "incident_id": 11,
                        "text": "she settled",
                        "source": "caregiver",
                    }
                ],
                "pattern": "similar time of day",
                "similarity": 0.9432,
                "rank_score": 0.91,
            }
        )

        self.assertIn("walked", text.casefold())
        self.assertIn("2 prior incidents", text.casefold())
        self.assertIn("caregiver reported", text.casefold())
        self.assertIn("possible repeated context", text.casefold())
        self.assertNotIn("0.9432", text)
        self.assertNotIn("0.91", text)
        self.assertNotIn("%", text)

    def test_guidance_card_has_honest_insufficient_history_state(self):
        from src import render

        text = render.guidance_card(
            {
                "status": "insufficient_history",
                "headline": "Not enough history yet",
                "history_count": 4,
                "action": None,
            }
        )

        self.assertIn("4 usable incidents", text.casefold())
        self.assertIn("not enough history", text.casefold())
        self.assertNotIn("try", text.casefold())


class IdentityCardTests(unittest.TestCase):
    def test_match_shows_name_and_band_without_debug_numbers(self):
        from src import render

        text = render.identity_card(
            {
                "status": "match",
                "display_name": "Baby A",
                "kind": "infant",
                "band": "weak",
                "score": 0.923456,
                "margin": 0.147837,
                "reasons": ["acoustically_consistent_with_enrolled_profile"],
            }
        )

        self.assertIn("baby a", text.casefold())
        self.assertIn("weak", text.casefold())
        self.assertNotIn("0.923456", text)
        self.assertNotIn("0.147837", text)
        self.assertNotIn("%", text)

    def test_uncertain_never_leaks_top_candidate_or_strong_band(self):
        from src import render

        text = render.identity_card(
            {
                "status": "uncertain",
                "display_name": None,
                "band": "strong",
                "score": 0.95,
                "reasons": ["close_top_profiles"],
                "candidates": [
                    {"display_name": "Prasshanna", "score": 0.95},
                    {"display_name": "Other adult", "score": 0.94},
                ],
                "retry_allowed": True,
            }
        )

        lowered = text.casefold()
        self.assertIn("could not separate", lowered)
        self.assertIn("record one more", lowered)
        self.assertNotIn("prasshanna", lowered)
        self.assertNotIn("other adult", lowered)
        self.assertNotIn("strong", lowered)
        self.assertNotIn("0.95", lowered)

    def test_one_profile_state_is_setup_guidance_not_recording_failure(self):
        from src import render

        text = render.identity_card(
            {
                "status": "uncertain",
                "reasons": [
                    "only_one_enrolled_profile",
                    "cannot_identify_without_a_comparison",
                    "enrol_a_second_profile_to_compare",
                ],
                "retry_allowed": False,
            }
        )

        self.assertIn("enroll a second profile", text.casefold())
        self.assertIn("comparison", text.casefold())
        self.assertNotIn("bad recording", text.casefold())
        self.assertNotIn("retry", text.casefold())

    def test_invalid_quiet_capture_gives_actionable_recording_copy(self):
        from src import render

        text = render.identity_card(
            {
                "status": "invalid",
                "reasons": ["near_silence"],
                "retry_allowed": True,
            }
        )

        self.assertIn("closer", text.casefold())
        self.assertIn("louder", text.casefold())
        self.assertNotIn("profile", text.casefold())

    def test_retry_exhausted_stays_unresolved_without_guessing(self):
        from src import render

        text = render.identity_card(
            {
                "status": "unresolved",
                "display_name": None,
                "reasons": ["retry_exhausted"],
                "candidates": [{"display_name": "Baby A"}],
                "retry_allowed": False,
            }
        )

        self.assertIn("could not identify", text.casefold())
        self.assertIn("choose an existing profile", text.casefold())
        self.assertNotIn("baby a", text.casefold())


if __name__ == "__main__":
    unittest.main()
