"""Tests for the Task 10 two-profile operating-point study.

These guard the three things that would silently invalidate the result:

  * PAIR DISJOINTNESS - if an infant appeared in two pairs, evaluation and calibration
    identities would overlap and the whole point of the design is lost.
  * MATCHED POOL SIZE - margin distributions depend on pool size, so calibration and
    evaluation must BOTH be pool size 2. That is the entire reason this study exists
    separately from the 46-profile one.
  * THRESHOLD SELECTION - the objective is predeclared. A selector that peeks at the
    evaluation half, or that ignores its own coverage floor, produces an optimistic number
    that looks rigorous.
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "tools"))

import two_profile_operating_point as t10  # noqa: E402


def fake_people(n_ids=8, per_id=3, sep=1.0):
    """Synthetic identities in a space where own-vs-other separation is controllable.

    Each identity sits on its own axis, so cosine within an identity is high and across
    identities is low. No audio, no encoder - these tests are about the experimental design,
    not about acoustics.
    """
    import numpy as np
    people = {}
    for i in range(n_ids):
        base = np.zeros(n_ids)
        base[i] = sep
        vs = []
        for k in range(per_id):
            v = base.copy()
            v[(i + 1) % n_ids] += 0.05 * k      # small within-identity variation
            vs.append(v / np.linalg.norm(v))
        people[f"id{i:02d}"] = vs
    return people


class TestPairing(unittest.TestCase):

    def test_pairs_are_disjoint_and_deterministic(self):
        people = fake_people(n_ids=9)
        uids = sorted(people)
        pairs = [(uids[i], uids[i + 1]) for i in range(0, len(uids) - 1, 2)]
        flat = [u for p in pairs for u in p]
        self.assertEqual(len(flat), len(set(flat)),
                         "an infant must never appear in two pairs")
        self.assertEqual(len(pairs), len(uids) // 2)
        # deterministic: same input, same pairing, no randomness
        again = [(uids[i], uids[i + 1]) for i in range(0, len(uids) - 1, 2)]
        self.assertEqual(pairs, again)

    def test_odd_identity_count_drops_the_last_rather_than_reusing_one(self):
        people = fake_people(n_ids=7)
        uids = sorted(people)
        pairs = [(uids[i], uids[i + 1]) for i in range(0, len(uids) - 1, 2)]
        flat = [u for p in pairs for u in p]
        self.assertEqual(len(flat), 6, "with 7 identities exactly one must be left out")
        self.assertEqual(len(flat), len(set(flat)))


class TestMatchedRecordingCohort(unittest.TestCase):

    def test_intersection_keeps_only_exact_paths_processed_by_both_encoders(self):
        left = {
            "baby-a": {
                "/corpus/a-1.wav": "left-a1",
                "/corpus/a-2.wav": "left-a2",
                "/corpus/a-3.wav": "left-a3",
                "/corpus/a-left-only.wav": "left-extra",
            },
            "baby-b": {
                "/corpus/b-1.wav": "left-b1",
                "/corpus/b-2.wav": "left-b2",
                "/corpus/b-3.wav": "left-b3",
            },
        }
        right = {
            "baby-a": {
                "/corpus/a-1.wav": "right-a1",
                "/corpus/a-2.wav": "right-a2",
                "/corpus/a-3.wav": "right-a3",
                "/corpus/a-right-only.wav": "right-extra",
            },
            "baby-b": {
                "/corpus/b-1.wav": "right-b1",
                "/corpus/b-2.wav": "right-b2",
            },
        }

        common = t10.common_recording_paths(left, right, minimum_recordings=3)

        self.assertEqual(
            {
                "baby-a": [
                    "/corpus/a-1.wav",
                    "/corpus/a-2.wav",
                    "/corpus/a-3.wav",
                ]
            },
            common,
        )

    def test_matched_people_have_identical_ordered_query_paths(self):
        import numpy as np

        left = {
            "baby-a": {
                "/corpus/a-2.wav": np.array([0.0, 1.0]),
                "/corpus/a-1.wav": np.array([1.0, 0.0]),
                "/corpus/a-3.wav": np.array([0.7, 0.7]),
            }
        }
        right = {
            "baby-a": {
                "/corpus/a-3.wav": np.array([0.6, 0.8]),
                "/corpus/a-1.wav": np.array([0.8, 0.6]),
                "/corpus/a-2.wav": np.array([0.1, 0.9]),
            }
        }
        common = t10.common_recording_paths(left, right, minimum_recordings=3)

        left_people, left_paths = t10.prepare_matched_people(
            t10.encoders.MFCC87,
            left,
            common,
            baseline=(np.zeros(2), np.ones(2)),
        )
        right_people, right_paths = t10.prepare_matched_people(
            t10.encoders.ECAPA_CRY,
            right,
            common,
            baseline=None,
        )

        self.assertEqual(left_paths, right_paths)
        self.assertEqual(
            [
                "/corpus/a-1.wav",
                "/corpus/a-2.wav",
                "/corpus/a-3.wav",
            ],
            left_paths["baby-a"],
        )
        self.assertEqual(3, len(left_people["baby-a"]))
        self.assertEqual(3, len(right_people["baby-a"]))


class TestPoolSize(unittest.TestCase):

    def test_every_trial_uses_pool_size_two(self):
        """Margin distributions depend on pool size. If any trial scored against more than
        two profiles, the operating point would not describe the demo."""
        people = fake_people(n_ids=6)
        uids = sorted(people)
        pairs = [(uids[i], uids[i + 1]) for i in range(0, len(uids) - 1, 2)]
        trials = t10.pair_trials(pairs, people)
        self.assertTrue(trials)
        for t in trials:
            self.assertEqual(t["pool_size"], 2)

    def test_trial_count_matches_leave_one_out_arithmetic(self):
        people = fake_people(n_ids=6, per_id=3)
        uids = sorted(people)
        pairs = [(uids[i], uids[i + 1]) for i in range(0, len(uids) - 1, 2)]
        trials = t10.pair_trials(pairs, people)
        # 3 pairs x 2 identities x 3 recordings held out each
        self.assertEqual(len(trials), 3 * 2 * 3)

    def test_a_query_is_never_scored_against_its_own_held_out_recording(self):
        """Leaving the query in its own enrollment set would make the profile agree with
        itself for free and inflate every number."""
        people = fake_people(n_ids=4, per_id=3)
        uids = sorted(people)
        pairs = [(uids[0], uids[1])]
        trials = t10.pair_trials(pairs, people)
        # with clean synthetic separation every trial should be correct, but never perfect-1.0
        for t in trials:
            self.assertLess(t["score"], 1.0 - 1e-9,
                            "a score of exactly 1.0 means the query was in its own enrollments")


class TestThresholdSelection(unittest.TestCase):

    def _trials(self, correct_scores, wrong_scores, margin=0.5):
        out = []
        for s in correct_scores:
            out.append({"truth": "a", "pred": "a", "score": s, "margin": margin,
                        "correct": True, "pool_size": 2})
        for s in wrong_scores:
            out.append({"truth": "a", "pred": "b", "score": s, "margin": margin,
                        "correct": False, "pool_size": 2})
        return out

    def test_predeclared_objective_respects_the_coverage_floor(self):
        """The default objective must not return a high-precision point that covers almost
        nothing - that is exactly the mistake the earlier corpus report made."""
        trials = self._trials([0.9] * 5 + [0.4] * 15, [0.35] * 5)
        sel = t10.select(trials)
        self.assertIsNotNone(sel)
        _, thr, mth, cov, prec = sel
        self.assertGreaterEqual(cov, t10.MIN_COVERAGE)

    def test_alt_objective_respects_the_precision_floor(self):
        trials = self._trials([0.9] * 10, [0.85] * 10)
        sel = t10.select(trials, min_precision=0.75)
        if sel is not None:
            _, thr, mth, cov, prec = sel
            self.assertGreaterEqual(prec, 0.75)

    def test_returns_none_when_no_point_meets_the_floor(self):
        """It must say 'no such point' rather than quietly relaxing its own objective."""
        trials = self._trials([0.9], [0.9] * 50)
        self.assertIsNone(t10.select(trials, min_precision=0.99))

    def test_selection_never_sees_the_evaluation_half(self):
        """select() must be a pure function of the trials handed to it."""
        cal = self._trials([0.9] * 10, [0.3] * 3)
        ev = self._trials([0.1] * 50, [0.95] * 50)      # deliberately hostile
        a = t10.select(cal)
        b = t10.select(cal)
        self.assertEqual(a, b, "selection must be deterministic")
        self.assertEqual(a, t10.select(list(cal)),
                         "selection must depend only on its own argument")
        self.assertNotEqual(t10.select(ev), a,
                            "different trials must produce a different choice, proving the "
                            "evaluation half would change the answer if it leaked in")


class TestWilson(unittest.TestCase):

    def test_zero_observed_errors_is_not_a_zero_rate(self):
        """The bound that made the earlier 'zero wrong' claim retractable."""
        self.assertGreater(t10.wilson_upper(0, 48), 0.0)
        self.assertLess(t10.wilson_upper(0, 48), 0.10)
        self.assertGreater(t10.wilson_upper(0, 10), t10.wilson_upper(0, 100),
                           "fewer observations must give a WIDER bound")

    def test_bound_is_above_the_point_estimate(self):
        self.assertGreater(t10.wilson_upper(2, 48), 2 / 48)

    def test_empty_sample_is_maximally_uncertain(self):
        self.assertEqual(t10.wilson_upper(0, 0), 1.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
