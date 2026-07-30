import os
import unittest
from tempfile import TemporaryDirectory

from src import diary, store


class InterventionTallyRenderingTests(unittest.TestCase):
    def test_diary_credits_only_the_final_action_for_settling(self):
        with TemporaryDirectory() as directory:
            db_path = os.path.join(directory, "diary.db")
            store.save_episode(
                {
                    "subject_id": "baby-tally",
                    "interventions": [
                        {"order": 1, "action": "checked diaper"},
                        {"order": 2, "action": "fed"},
                    ],
                    "outcome": "feeding settled her",
                    "outcome_src": "caregiver",
                    "worked": True,
                },
                db_path,
            )

            markdown = diary.render_markdown("baby-tally", db_path)

        self.assertIn("| checked diaper | 1 | 0 |", markdown)
        self.assertIn("| fed | 1 | 1 |", markdown)
        self.assertIn("final action", markdown.casefold())


if __name__ == "__main__":
    unittest.main()
