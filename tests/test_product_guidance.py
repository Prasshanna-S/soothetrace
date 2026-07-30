import unittest

from src import guidance


def _scenario(
    episode_id,
    *,
    worked=True,
    interventions=None,
    outcome="she settled",
    outcome_src="caregiver",
    time_similarity=0.0,
    notes_similarity=0.0,
):
    return {
        "episode_id": episode_id,
        "worked": worked,
        "interventions": interventions or [],
        "outcome": outcome,
        "outcome_src": outcome_src,
        "components": {
            "acoustic": 0.9,
            "time_of_day": time_similarity,
            "notes": notes_similarity,
        },
        "rank_score": 0.91,
        "similarity": 0.88,
        "band": "weak",
    }


class GuidanceTests(unittest.TestCase):
    def test_selects_final_action_from_resolved_scenarios(self):
        scenarios = [
            _scenario(
                11,
                interventions=[
                    {"order": 1, "action": "checked diaper", "evidence": "checked her diaper"},
                    {"order": 2, "action": "walked", "evidence": "walked with her"},
                ],
            ),
            _scenario(
                7,
                interventions=[
                    {"order": 1, "action": "walked", "evidence": "walked around"},
                ],
            ),
            _scenario(
                3,
                interventions=[
                    {"order": 1, "action": "offered feeding", "evidence": "gave a bottle"},
                ],
            ),
        ]
        tally = [
            {"action": "offered feeding", "tried": 8, "worked": 7, "worked_last": 7},
            {"action": "walked", "tried": 2, "worked": 2, "worked_last": 2},
        ]

        result = guidance.build_guidance(
            4,
            scenarios,
            tally,
            history_count=6,
        )

        self.assertEqual("grounded", result["status"])
        self.assertEqual("walked", result["action"])
        self.assertEqual(2, result["support_count"])
        self.assertEqual([11, 7], result["incident_ids"])
        self.assertNotIn("checked diaper", result["action"])

    def test_returns_plain_language_output_bound_to_recorded_history(self):
        scenarios = [
            _scenario(
                11,
                interventions=[
                    {"order": 1, "action": "walked", "evidence": "walked with her"},
                ],
            ),
            _scenario(
                7,
                interventions=[
                    {"order": 1, "action": "walked", "evidence": "walked around"},
                ],
            ),
        ]

        result = guidance.build_guidance(
            4,
            scenarios,
            [],
            history_count=6,
        )

        self.assertEqual(
            "This resembles earlier incidents for this profile.",
            result["interpretation"],
        )
        self.assertEqual("What helped before: walked.", result["recommendation"])
        self.assertEqual(
            "Supported by 2 similar recorded incidents.",
            result["evidence_summary"],
        )
        rendered = str(result).casefold()
        self.assertNotIn("hunger", rendered)
        self.assertNotIn("pain", rendered)
        self.assertNotIn("diagnosis", rendered)

    def test_tally_cannot_introduce_an_action_absent_from_selected_history(self):
        scenarios = [
            _scenario(
                11,
                worked=False,
                interventions=[
                    {"order": 1, "action": "walked", "evidence": "walked with her"},
                ],
            )
        ]
        tally = [
            {"action": "rocked", "tried": 20, "worked": 20, "worked_last": 20}
        ]

        result = guidance.build_guidance(
            4,
            scenarios,
            tally,
            history_count=6,
        )

        self.assertEqual("no_helpful_history", result["status"])
        self.assertIsNone(result["action"])
        self.assertNotIn("rocked", str(result).casefold())

    def test_reports_only_outcomes_supporting_the_selected_action(self):
        scenarios = [
            _scenario(
                11,
                interventions=[
                    {"order": 1, "action": "walked", "evidence": "walked with her"},
                ],
                outcome="she settled",
                outcome_src="caregiver",
            ),
            _scenario(
                7,
                interventions=[
                    {"order": 1, "action": "walked", "evidence": "walked around"},
                ],
                outcome="stopped crying",
                outcome_src="inferred",
            ),
            _scenario(
                3,
                interventions=[
                    {"order": 1, "action": "offered feeding", "evidence": "gave a bottle"},
                ],
                outcome="fell asleep",
                outcome_src="caregiver",
            ),
        ]

        result = guidance.build_guidance(
            4,
            scenarios,
            [],
            history_count=6,
        )

        self.assertEqual(
            [
                {"incident_id": 11, "text": "she settled", "source": "caregiver"},
                {"incident_id": 7, "text": "stopped crying", "source": "inferred"},
            ],
            result["outcomes"],
        )

    def test_requires_two_supporting_incidents_for_a_context_pattern(self):
        one_similar = [
            _scenario(
                11,
                interventions=[
                    {"order": 1, "action": "walked", "evidence": "walked with her"},
                ],
                time_similarity=0.95,
            ),
            _scenario(
                7,
                interventions=[
                    {"order": 1, "action": "walked", "evidence": "walked around"},
                ],
                time_similarity=0.2,
            ),
        ]
        two_similar = [
            {**one_similar[0]},
            {
                **one_similar[1],
                "components": {**one_similar[1]["components"], "time_of_day": 0.8},
            },
        ]

        first = guidance.build_guidance(4, one_similar, [], history_count=6)
        second = guidance.build_guidance(4, two_similar, [], history_count=6)

        self.assertIsNone(first["pattern"])
        self.assertEqual("similar time of day", second["pattern"])

    def test_returns_insufficient_history_before_six_incidents(self):
        result = guidance.build_guidance(
            4,
            [
                _scenario(
                    11,
                    interventions=[
                        {"order": 1, "action": "walked", "evidence": "walked"},
                    ],
                )
            ],
            [],
            history_count=5,
        )

        self.assertEqual("insufficient_history", result["status"])
        self.assertEqual(5, result["history_count"])
        self.assertIsNone(result["action"])

    def test_context_is_never_turned_into_a_cause(self):
        result = guidance.build_guidance(
            4,
            [
                _scenario(
                    11,
                    interventions=[
                        {"order": 1, "action": "walked", "evidence": "walked"},
                    ],
                ),
                _scenario(
                    7,
                    interventions=[
                        {"order": 1, "action": "walked", "evidence": "walked"},
                    ],
                ),
            ],
            [],
            history_count=6,
            current_context={"tags": ["last_feed_over_4h"]},
        )

        rendered = str(result).casefold()
        self.assertNotIn("hungry", rendered)
        self.assertNotIn("hunger", rendered)
        self.assertNotIn("because", rendered)

    def test_malformed_debug_components_do_not_break_grounded_history(self):
        scenario = _scenario(
            11,
            interventions=[
                {"order": 1, "action": "walked", "evidence": "walked"},
            ],
        )
        scenario["components"] = {"time_of_day": "not-a-number", "notes": object()}

        result = guidance.build_guidance(
            4,
            [scenario],
            [{"action": "walked", "worked_last": "not-a-number"}],
            history_count=6,
        )

        self.assertEqual("grounded", result["status"])
        self.assertEqual("walked", result["action"])
        self.assertIsNone(result["pattern"])


if __name__ == "__main__":
    unittest.main()
