import os
import sys
import unittest


sys.path.insert(
    0,
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"),
)

import human_session_eval as evaluator  # noqa: E402


class HumanSessionEvaluationTests(unittest.TestCase):
    def test_summary_separates_confirmed_and_directional_results(self):
        rows = [
            {"expected": "A", "result_type": "matched", "result_name": "A"},
            {"expected": "B", "result_type": "leaning", "result_name": "B"},
            {"expected": "C", "result_type": "leaning", "result_name": "A"},
            {"expected": "C", "result_type": "unresolved", "result_name": None},
        ]

        summary = evaluator.summarize(rows)

        self.assertEqual(1, summary["confirmed_correct"])
        self.assertEqual(0, summary["confirmed_wrong"])
        self.assertEqual(1, summary["leaning_correct"])
        self.assertEqual(1, summary["leaning_wrong"])
        self.assertEqual(1, summary["unresolved"])
        self.assertEqual(0.5, summary["direction_correct_rate"])

    def test_manifest_rejects_duplicate_profile_ids(self):
        manifest = {
            "kind": "human_imitation",
            "profiles": [
                {"id": "a", "display_name": "A", "files": ["a.wav"]},
                {"id": "a", "display_name": "B", "files": ["b.wav"]},
            ],
        }

        with self.assertRaisesRegex(ValueError, "duplicate profile id"):
            evaluator.validate_manifest(manifest)

    def test_manifest_accepts_any_number_of_distinct_profiles(self):
        manifest = {
            "kind": "human_imitation",
            "profiles": [
                {"id": "a", "display_name": "A", "files": ["a.wav"]},
                {"id": "b", "display_name": "B", "files": ["b.wav"]},
                {"id": "c", "display_name": "C", "files": ["c.wav"]},
            ],
        }

        profiles = evaluator.validate_manifest(manifest)

        self.assertEqual(["a", "b", "c"], [profile["id"] for profile in profiles])

    def test_session_labels_continue_past_z(self):
        self.assertEqual("Person A", evaluator.session_label(1))
        self.assertEqual("Person Z", evaluator.session_label(26))
        self.assertEqual("Person AA", evaluator.session_label(27))

    def test_discovery_summary_counts_new_and_known_turns_separately(self):
        rows = [
            {
                "phase": "first_encounter",
                "expected": "Person A",
                "result_type": "new",
                "result_name": "Person A",
            },
            {
                "phase": "first_encounter",
                "expected": "Person B",
                "result_type": "matched",
                "result_name": "Person A",
            },
            {
                "phase": "known_turn",
                "expected": "Person A",
                "result_type": "matched",
                "result_name": "Person A",
            },
            {
                "phase": "known_turn",
                "expected": "Person A",
                "result_type": "new",
                "result_name": "Person C",
            },
        ]

        summary = evaluator.summarize_discovery(rows)

        self.assertEqual(1, summary["new_people_correct"])
        self.assertEqual(1, summary["new_people_missed"])
        self.assertEqual(1, summary["known_turns_correct"])
        self.assertEqual(1, summary["known_turns_confirmed_correct"])
        self.assertEqual(0, summary["known_turns_leaning_correct"])
        self.assertEqual(1, summary["known_turns_split_as_new"])


if __name__ == "__main__":
    unittest.main()
