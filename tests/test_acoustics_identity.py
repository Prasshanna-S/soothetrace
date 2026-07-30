"""Tests for identity.py and retrieve.find_scenarios(). Owned by acoustics workstream.

The tests that matter most here are the ones asserting what the system REFUSES to do:

* `test_close_profiles_return_uncertain_not_a_guess` - the margin gate. On the real live
  data this is what turned the single wrong 2-class decision into "uncertain" and produced
  0 wrong answers across 15 trials. If this regresses, the demo can name the wrong baby.
* `test_identity_ignores_context` - identity must be acoustic ONLY. Context leaking in would
  make a blind reveal a fraud, invisibly.
* `test_duplicate_audio_is_refused` - otherwise a profile agrees with itself for free.
"""
from __future__ import annotations

import math
import os
import sys
import tempfile
import unittest
import wave
import struct
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

import config       # noqa: E402
import fingerprint  # noqa: E402
import identity     # noqa: E402
import retrieve     # noqa: E402
import store        # noqa: E402


def tone_wav(path, freq=400.0, seconds=2.0, amp=0.3, sr=16000, harmonic=0.0):
    n = int(seconds * sr)
    frames = bytearray()
    for i in range(n):
        t = i / sr
        v = amp * math.sin(2 * math.pi * freq * t)
        if harmonic:
            v += harmonic * amp * math.sin(2 * math.pi * freq * 2.5 * t)
        frames += struct.pack("<h", int(max(-1.0, min(1.0, v)) * 32767))
    with wave.open(path, "wb") as fh:
        fh.setnchannels(1); fh.setsampwidth(2); fh.setframerate(sr)
        fh.writeframes(bytes(frames))
    return path


class IdentityBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.d = self._tmp.name
        self.db = os.path.join(self.d, "t.db")
        store.init_db(self.db)
        # a neutral population baseline so normalization is well-defined
        store.save_baseline(config.POPULATION_KEY, [0.0] * fingerprint.DIM,
                            [1.0] * fingerprint.DIM, 400, self.db)

    def tearDown(self):
        self._tmp.cleanup()

    def wav(self, name, **kw):
        return tone_wav(os.path.join(self.d, name), **kw)


class TestProfiles(IdentityBase):

    def test_create_and_list(self):
        p = identity.create_profile("Baby A", identity.KIND_INFANT, db_path=self.db)
        self.assertTrue(p["id"])
        self.assertEqual(p["status"], "provisional")
        self.assertEqual(p["enrollments"], 0)
        self.assertEqual(len(identity.list_profiles(self.db)), 1)

    def test_rejects_bad_kind_and_empty_name(self):
        self.assertEqual(identity.create_profile("X", "cat", db_path=self.db), {})
        self.assertEqual(identity.create_profile("", "infant", db_path=self.db), {})

    def test_profile_becomes_ready_only_at_two_enrollments(self):
        """A profile is the SET of its enrollments. One clip cannot distinguish
        within-source from between-source variation."""
        p = identity.create_profile("A", db_path=self.db)
        r1 = identity.enroll(p["id"], self.wav("a1.wav", freq=420), db_path=self.db)
        self.assertEqual(r1["profile_status"], "provisional")
        r2 = identity.enroll(p["id"], self.wav("a2.wav", freq=430), db_path=self.db)
        self.assertEqual(r2["profile_status"], "ready")
        self.assertEqual(r2["enrollments"], 2)

    def test_duplicate_audio_is_refused(self):
        p = identity.create_profile("A", db_path=self.db)
        w = self.wav("a1.wav", freq=420)
        self.assertEqual(identity.enroll(p["id"], w, db_path=self.db)["status"], "enrolled")
        dup = identity.enroll(p["id"], w, db_path=self.db)
        self.assertEqual(dup["status"], "rejected")
        self.assertEqual(dup["reason"], "duplicate_audio")

    def test_duplicate_audio_is_refused_across_profiles_by_default(self):
        first = identity.create_profile("A", db_path=self.db)
        second = identity.create_profile("B", db_path=self.db)
        audio = self.wav("shared.wav", freq=420)
        self.assertEqual(
            "enrolled",
            identity.enroll(first["id"], audio, db_path=self.db)["status"],
        )

        duplicate = identity.enroll(second["id"], audio, db_path=self.db)

        self.assertEqual("rejected", duplicate["status"])
        self.assertEqual(
            "audio_already_enrolled_to_another_profile",
            duplicate["reason"],
        )

    def test_silent_audio_is_rejected_with_a_reason(self):
        p = identity.create_profile("A", db_path=self.db)
        r = identity.enroll(p["id"], self.wav("s.wav", amp=0.0), db_path=self.db)
        self.assertEqual(r["status"], "rejected")
        self.assertEqual(r["reason"], "no_usable_voiced_audio")

    def test_delete_removes_enrollments_and_managed_audio_only(self):
        p = identity.create_profile("A", db_path=self.db)
        outside = self.wav("outside.wav", freq=420)   # not under AUDIO_DIR
        identity.enroll(p["id"], outside, db_path=self.db)
        res = identity.delete_profile(p["id"], db_path=self.db)
        self.assertTrue(res["deleted"])
        self.assertEqual(identity.get_profile(p["id"], self.db), {})
        self.assertTrue(os.path.exists(outside),
                        "audio outside AUDIO_DIR must never be deleted")


class TestIdentify(IdentityBase):

    def _profile(self, name, freq, n=2, harmonic=0.0):
        p = identity.create_profile(name, db_path=self.db)
        for i in range(n):
            identity.enroll(p["id"], self.wav(f"{name}{i}.wav", freq=freq + i * 3,
                                              harmonic=harmonic), db_path=self.db)
        return p

    def test_no_profiles_returns_uncertain_not_a_crash(self):
        r = identity.identify(self.wav("q.wav", freq=400), db_path=self.db)
        self.assertEqual(r["status"], identity.STATUS_UNCERTAIN)
        self.assertIn("no_enrolled_profiles", r["reasons"])

    def test_missing_audio_is_invalid(self):
        r = identity.identify("/nope/none.wav", db_path=self.db)
        self.assertEqual(r["status"], identity.STATUS_INVALID)
        self.assertIn("missing_audio", r["reasons"])

    def test_silence_is_invalid_not_a_match(self):
        self._profile("A", 420)
        r = identity.identify(self.wav("sil.wav", amp=0.0), db_path=self.db)
        self.assertEqual(r["status"], identity.STATUS_INVALID)
        self.assertIn("no_usable_voiced_audio", r["reasons"])

    def test_no_baseline_refuses_to_compare(self):
        """Without a baseline, raw cosine would score ~0.99 for everything."""
        import sqlite3
        self._profile("A", 420)
        con = sqlite3.connect(self.db); con.execute("DELETE FROM baseline"); con.commit(); con.close()
        r = identity.identify(self.wav("q.wav", freq=420), db_path=self.db)
        self.assertEqual(r["status"], identity.STATUS_INVALID)
        self.assertIn("no_population_baseline", r["reasons"])

    def test_result_shape_is_the_contract(self):
        self._profile("A", 420)
        r = identity.identify(self.wav("q.wav", freq=421), db_path=self.db)
        for key in ("status", "profile_id", "display_name", "band", "score", "margin",
                    "support", "reasons", "candidates", "versions"):
            self.assertIn(key, r)
        self.assertIn("encoder", r["versions"])
        self.assertIn("calibration", r["versions"])

    def test_close_profiles_return_uncertain_not_a_guess(self):
        """THE margin gate. Two near-identical profiles must produce `uncertain`.

        On real live data this is what converted the one wrong 2-class decision
        (margin 0.0486) into a retry, giving 0 wrong answers across 15 trials.
        """
        # NOTE: A and B must have DIFFERENT audio bytes but near-identical acoustics.
        # An earlier version of this test used byte-identical files, which enroll() now
        # correctly refuses (audio_already_enrolled_to_another_profile) - so the scenario
        # became unreachable and the test silently stopped exercising the margin gate.
        self._profile("A", 420.0)
        self._profile("B", 420.4)        # distinct bytes, indistinguishable spectrum
        r = identity.identify(self.wav("q.wav", freq=420.2), db_path=self.db)
        self.assertEqual(len([p for p in identity.list_profiles(self.db)
                              if p["enrollments"] >= 2]), 2,
                         "both profiles must really be enrolled or this tests nothing")
        self.assertNotEqual(r["status"], identity.STATUS_MATCH,
                            "two indistinguishable profiles must never yield a confident match")
        if r["margin"] is not None:
            self.assertLess(r["margin"], identity.load_calibration()["margin_threshold"])

    def test_identity_ignores_context(self):
        """Identity must be acoustic ONLY - time, notes and outcomes may never touch it.

        Context leaking into identity would make a blind reveal a fraud, and it would be
        invisible from the outside.
        """
        self._profile("A", 420)
        q = self.wav("q.wav", freq=423)
        a = identity.identify(q, db_path=self.db)
        # add episodes loaded with context under the same-named subject
        for h in range(3):
            store.save_episode({"subject_id": "A", "fingerprint": [0.5] * fingerprint.DIM,
                                "context": {"hour_local": 19, "tags": ["overtired"]},
                                "worked": True, "outcome": "rocking"}, self.db)
        b = identity.identify(q, db_path=self.db)
        self.assertEqual(a["status"], b["status"])
        self.assertAlmostEqual(a["score"], b["score"], places=9)

    def test_query_is_audited(self):
        import sqlite3
        self._profile("A", 420)
        identity.identify(self.wav("q.wav", freq=421), db_path=self.db)
        con = sqlite3.connect(self.db)
        n = con.execute("SELECT COUNT(*) FROM identity_query").fetchone()[0]
        con.close()
        self.assertGreaterEqual(n, 1, "every identity decision must be auditable")

    def test_kind_filter_isolates_families(self):
        self._profile("A", 420)
        r = identity.identify(self.wav("q.wav", freq=420),
                              kind=identity.KIND_IMITATION, db_path=self.db)
        self.assertEqual(r["status"], identity.STATUS_UNCERTAIN)
        self.assertIn("no_enrolled_profiles", r["reasons"])


class TestFindScenarios(IdentityBase):

    def _episodes(self, subject="s1", n=8, hour=19, tags=None):
        for i in range(n):
            store.save_episode({
                "subject_id": subject,
                "started_at": f"2026-07-{i+1:02d}T{hour:02d}:20:00-04:00",
                "fingerprint": [math.sin(0.3 * (i + 1) * (j + 1)) for j in range(fingerprint.DIM)],
                "context": {"hour_local": hour if i % 2 == 0 else (hour + 6) % 24,
                            "tags": tags if i % 2 == 0 else []},
                "interventions": [{"order": 1, "action": "rocking", "evidence": "rock"}],
                "outcome": "rocking worked", "outcome_src": "caregiver", "worked": True,
            }, self.db)

    def test_time_of_day_is_cyclic(self):
        self.assertAlmostEqual(retrieve._time_of_day_similarity(23, 1), 1 - 2 / 12, places=6)
        self.assertEqual(retrieve._time_of_day_similarity(19, 7), 0.0)
        self.assertEqual(retrieve._time_of_day_similarity(19, 19), 1.0)
        self.assertIsNone(retrieve._time_of_day_similarity(None, 5))

    def test_notes_similarity(self):
        self.assertEqual(retrieve._notes_similarity(["Fed"], ["fed"]), 1.0)
        self.assertAlmostEqual(retrieve._notes_similarity(["a", "b"], ["b"]), 0.5)
        self.assertIsNone(retrieve._notes_similarity([], ["b"]))

    def test_returns_empty_below_min_episodes(self):
        self._episodes(n=2)
        self.assertEqual(retrieve.find_scenarios("s1", [0.1] * fingerprint.DIM,
                                                 db_path=self.db), [])

    def test_ranks_and_exposes_contributions(self):
        self._episodes(n=8, tags=["overtired"])
        got = retrieve.find_scenarios("s1", [0.2] * fingerprint.DIM,
                                      {"hour_local": 19, "tags": ["overtired"]},
                                      k=3, db_path=self.db)
        self.assertTrue(got)
        self.assertLessEqual(len(got), 3)
        for r in got:
            self.assertIn("rank_score", r)
            self.assertIn("contributions", r)
            self.assertIn("acoustic", r["components"])
            self.assertTrue(r["contributions"])
        scores = [r["rank_score"] for r in got]
        self.assertEqual(scores, sorted(scores, reverse=True), "must be best-first")

    def test_missing_context_renormalizes_and_does_not_crash(self):
        self._episodes(n=8)
        got = retrieve.find_scenarios("s1", [0.2] * fingerprint.DIM, None,
                                      k=2, db_path=self.db)
        self.assertTrue(got)
        for r in got:
            self.assertAlmostEqual(sum(r["weights_used"].values()), 1.0, places=6)

    def test_never_returns_another_subjects_episodes(self):
        self._episodes(subject="s1", n=8)
        self._episodes(subject="s2", n=8)
        ids_s2 = {ep["id"] for ep in store.list_episodes("s2", self.db)}
        got = retrieve.find_scenarios("s1", [0.2] * fingerprint.DIM, None,
                                      k=5, db_path=self.db)
        for r in got:
            self.assertNotIn(r["episode_id"], ids_s2,
                             "identity gating must be absolute")


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TestAttemptLifecycle(IdentityBase):
    """`independent-retry-confirmation-v1` + refinement 5a.

    The tests that matter here assert what the lifecycle REFUSES:
    a retry cannot be spent when no comparison exists, a disagreeing retry cannot resolve,
    a resolved attempt is immutable, a human resolution is never counted as a machine match,
    and a human resolution never enrols the capture.
    """

    def _two_profiles(self):
        a = identity.create_profile("A", db_path=self.db)
        b = identity.create_profile("B", db_path=self.db)
        for i in range(2):
            identity.enroll(a["id"], self.wav(f"a{i}.wav", freq=420 + i * 4), db_path=self.db)
            identity.enroll(b["id"], self.wav(f"b{i}.wav", freq=900 + i * 4), db_path=self.db)
        return a, b

    def _novelty_result(self, profile_id):
        return {
            "status": identity.STATUS_UNCERTAIN,
            "profile_id": None,
            "display_name": None,
            "band": "none",
            "score": 0.2,
            "margin": 0.1,
            "support": None,
            "reasons": [
                "below_accept_threshold",
                "new_or_unenrolled_source",
            ],
            "candidates": [
                {
                    "profile_id": profile_id,
                    "display_name": "A",
                    "score": 0.2,
                }
            ],
            "kind": identity.KIND_IMITATION,
            "pool_size": 2,
            "quality": {},
            "versions": {
                "encoder": identity.encoder_for(identity.KIND_IMITATION),
                "calibration": "test",
                "aggregation": identity.AGGREGATION_VERSION,
                "cohort": identity.COHORT_VERSION,
            },
        }

    def test_begin_rejects_bad_kind(self):
        self.assertIn("error", identity.begin_identity_attempt("cat", db_path=self.db))

    def test_candidate_ids_are_display_only_and_recorded(self):
        """Narrowing the SCORED pool would remove a runner-up and inflate the margin."""
        self._two_profiles()
        at = identity.begin_identity_attempt(identity.KIND_INFANT, candidate_profile_ids=[1],
                                             db_path=self.db)
        self.assertEqual(at["candidate_profile_ids"], [1])
        r = identity.add_identity_capture(at["id"], self.wav("q.wav", freq=421),
                                          db_path=self.db)
        cap = r["captures"][0]
        self.assertGreaterEqual(cap["pool_size"], 2,
                                "scoring must use the FULL pool regardless of display filter")

    def test_invalid_capture_does_not_consume_the_retry(self):
        self._two_profiles()
        at = identity.begin_identity_attempt(identity.KIND_INFANT, db_path=self.db)
        r = identity.add_identity_capture(at["id"], self.wav("sil.wav", amp=0.0),
                                          db_path=self.db)
        self.assertEqual(r["capture_status"], identity.STATUS_INVALID)
        self.assertIs(r["retry_consumed"], False)
        self.assertEqual(r["valid_captures"], 0)
        self.assertEqual(r["status"], identity.ATTEMPT_OPEN)
        self.assertTrue(r["retry_allowed"])
        # and a real first capture is still accepted afterwards
        r2 = identity.add_identity_capture(at["id"], self.wav("q.wav", freq=421),
                                          db_path=self.db)
        self.assertNotIn("error", r2)

    def test_one_profile_attempt_gets_no_retry(self):
        """Another recording cannot create a comparison that does not exist."""
        p = identity.create_profile("Solo", db_path=self.db)
        for i in range(2):
            identity.enroll(p["id"], self.wav(f"s{i}.wav", freq=420 + i * 4), db_path=self.db)
        at = identity.begin_identity_attempt(identity.KIND_INFANT, db_path=self.db)
        r = identity.add_identity_capture(at["id"], self.wav("q.wav", freq=421),
                                          db_path=self.db)
        self.assertIn("only_one_enrolled_profile", r["reasons"])
        self.assertFalse(r["retry_allowed"])
        self.assertEqual(r["status"], identity.ATTEMPT_UNRESOLVED)
        denied = identity.retry_identity_attempt(at["id"], self.wav("q2.wav", freq=421),
                                                 db_path=self.db)
        self.assertIn("error", denied)

    def test_resolved_attempt_is_immutable(self):
        self._two_profiles()
        at = identity.begin_identity_attempt(identity.KIND_INFANT, db_path=self.db)
        identity.add_identity_capture(at["id"], self.wav("q.wav", freq=421), db_path=self.db)
        a = identity.get_identity_attempt(at["id"], self.db)
        if a["status"] == identity.ATTEMPT_OPEN:
            identity.retry_identity_attempt(at["id"], self.wav("q2.wav", freq=422),
                                            db_path=self.db)
        a = identity.get_identity_attempt(at["id"], self.db)
        self.assertNotEqual(a["status"], identity.ATTEMPT_OPEN)
        again = identity.add_identity_capture(at["id"], self.wav("q3.wav", freq=421),
                                             db_path=self.db)
        self.assertIn("error", again)

    def test_retry_before_a_first_capture_is_refused(self):
        self._two_profiles()
        at = identity.begin_identity_attempt(identity.KIND_INFANT, db_path=self.db)
        r = identity.retry_identity_attempt(at["id"], self.wav("q.wav", freq=421),
                                           db_path=self.db)
        self.assertEqual(r.get("error"), "no_first_capture")

    def test_human_resolution_is_marked_human_and_never_enrols(self):
        """Without this separation the audit cannot tell what the SYSTEM identified from
        what a person told it, and every accuracy figure becomes unfalsifiable."""
        a, _b = self._two_profiles()
        before = identity.get_profile(a["id"], self.db)["enrollments"]
        at = identity.begin_identity_attempt(identity.KIND_INFANT, db_path=self.db)
        identity.add_identity_capture(at["id"], self.wav("q.wav", freq=700), db_path=self.db)
        res = identity.resolve_identity_attempt(at["id"], confirmed_profile_id=a["id"],
                                                db_path=self.db)
        self.assertEqual(res["status"], identity.ATTEMPT_MATCH)
        self.assertEqual(res["resolution_source"], "human")
        self.assertEqual(res["resolution_path"], "human")
        self.assertIn("human_confirmed_not_machine_identified", res["reasons"])
        self.assertEqual(identity.get_profile(a["id"], self.db)["enrollments"], before,
                         "a human resolution must NEVER enrol the capture")

    def test_human_resolution_rejects_unknown_profile(self):
        self._two_profiles()
        at = identity.begin_identity_attempt(identity.KIND_INFANT, db_path=self.db)
        identity.add_identity_capture(at["id"], self.wav("q.wav", freq=700), db_path=self.db)
        self.assertIn("error", identity.resolve_identity_attempt(at["id"], 99999,
                                                                 db_path=self.db))

    def test_closing_without_a_profile_records_unresolved(self):
        self._two_profiles()
        at = identity.begin_identity_attempt(identity.KIND_INFANT, db_path=self.db)
        identity.add_identity_capture(at["id"], self.wav("q.wav", freq=700), db_path=self.db)
        res = identity.resolve_identity_attempt(at["id"], None, db_path=self.db)
        self.assertEqual(res["status"], identity.ATTEMPT_UNRESOLVED)
        self.assertEqual(res["resolution_source"], "human")
        self.assertIn("closed_without_resolution", res["reasons"])

    def test_every_capture_persists_its_provenance(self):
        """Digest, three distinct paths, quality, candidates, reasons and versions."""
        self._two_profiles()
        at = identity.begin_identity_attempt(identity.KIND_INFANT, db_path=self.db)
        w = self.wav("q.wav", freq=421)
        identity.add_identity_capture(at["id"], w, capture_metadata={
            "source_path": "/uploads/raw.m4a", "canonical_path": "/managed/raw.wav",
            "device": "iPhone", "ingest_version": "v1"}, db_path=self.db)
        cap = identity.get_identity_attempt(at["id"], self.db)["captures"][0]
        self.assertEqual(cap["identity_audio_path"], w)
        self.assertEqual(cap["source_audio_path"], "/uploads/raw.m4a")
        self.assertEqual(cap["canonical_audio_path"], "/managed/raw.wav")
        self.assertEqual(len(cap["audio_sha256"]), 64)
        self.assertEqual(cap["capture_metadata"]["device"], "iPhone")
        self.assertIn("voiced_fraction", cap["quality"])
        self.assertIsNotNone(cap["reasons"])
        self.assertIsNotNone(cap["encoder_version"])
        self.assertIsNotNone(cap["calibration_version"])
        self.assertEqual(cap["aggregation_version"], identity.AGGREGATION_VERSION)
        self.assertIsNotNone(cap["pool_size"])

    def test_retry_bar_is_stricter_than_a_first_capture(self):
        """5a: two chances at the normal bar would take attempt FAR from ~0.071 to ~0.125."""
        cal = identity.load_calibration(identity.KIND_INFANT)
        self.assertEqual(identity.RETRY_BAR_MULTIPLIER, 2.0)
        self.assertGreater(cal["margin_threshold"] * identity.RETRY_BAR_MULTIPLIER,
                           cal["margin_threshold"])

    def test_no_such_attempt_is_an_error_not_a_crash(self):
        for fn in (identity.add_identity_capture, identity.retry_identity_attempt):
            self.assertIn("error", fn(999999, self.wav("q.wav", freq=421), db_path=self.db))
        self.assertIn("error", identity.resolve_identity_attempt(999999, db_path=self.db))
        self.assertEqual(identity.get_identity_attempt(999999, self.db), {})

    def test_retry_with_identical_audio_is_refused_by_the_BACKEND(self):
        """A retry is only evidence if it is a NEW recording.

        Re-submitting identical bytes yields an identical embedding, so
        'capture 2 must independently pass and agree with capture 1' collapses into
        'capture 1 scored twice' and the attempt resolves on evidence it never had.

        The client cannot be the guard: a file picker hands back a fresh clip id for the same
        bytes, which defeats any client-side check. So this is enforced in the store.
        """
        self._two_profiles()
        at = identity.begin_identity_attempt(identity.KIND_INFANT, db_path=self.db)
        q = self.wav("q.wav", freq=700)          # deliberately unlike either profile
        first = identity.add_identity_capture(at["id"], q, db_path=self.db)
        if first.get("capture_status") != identity.STATUS_UNCERTAIN:
            self.skipTest("first capture did not abstain, so there is no retry to test")
        same = identity.retry_identity_attempt(at["id"], q, db_path=self.db)
        self.assertEqual(same.get("error"), "retry_audio_identical_to_earlier_capture")
        # ...and a genuinely different recording is still accepted
        other = identity.retry_identity_attempt(at["id"], self.wav("q2.wav", freq=702),
                                               db_path=self.db)
        self.assertNotIn("error", other)

    def test_retry_digest_guard_survives_a_copied_file(self):
        """Same bytes at a different PATH must also be refused - copying a file is the
        easiest possible way to defeat a path-based check."""
        import shutil
        self._two_profiles()
        at = identity.begin_identity_attempt(identity.KIND_INFANT, db_path=self.db)
        q = self.wav("orig.wav", freq=700)
        first = identity.add_identity_capture(at["id"], q, db_path=self.db)
        if first.get("capture_status") != identity.STATUS_UNCERTAIN:
            self.skipTest("first capture did not abstain")
        copy = os.path.join(self.d, "copied.wav")
        shutil.copyfile(q, copy)
        res = identity.retry_identity_attempt(at["id"], copy, db_path=self.db)
        self.assertEqual(res.get("error"), "retry_audio_identical_to_earlier_capture")

    def test_two_consistent_novelty_captures_confirm_a_new_profile_candidate(self):
        a, _b = self._two_profiles()
        attempt = identity.begin_identity_attempt(
            identity.KIND_IMITATION,
            db_path=self.db,
        )
        first_audio = self.wav("new-person-1.wav", freq=1200)
        retry_audio = self.wav("new-person-2.wav", freq=1210)
        with (
            patch.object(
                identity,
                "identify",
                side_effect=[
                    self._novelty_result(a["id"]),
                    self._novelty_result(a["id"]),
                ],
            ),
            patch.object(
                identity,
                "_novelty_pair_consistency",
                return_value={"consistent": True, "reasons": ["novelty_pair_consistent"]},
            ),
        ):
            first = identity.add_identity_capture(
                attempt["id"],
                first_audio,
                db_path=self.db,
            )
            self.assertTrue(first["retry_allowed"])
            result = identity.retry_identity_attempt(
                attempt["id"],
                retry_audio,
                db_path=self.db,
            )

        self.assertEqual(identity.ATTEMPT_UNRESOLVED, result["status"])
        self.assertIn("new_profile_candidate_confirmed", result["reasons"])
        self.assertIn("novelty_pair_consistent", result["reasons"])

    def test_two_inconsistent_novelty_captures_do_not_confirm_a_new_profile(self):
        a, _b = self._two_profiles()
        attempt = identity.begin_identity_attempt(
            identity.KIND_IMITATION,
            db_path=self.db,
        )
        first_audio = self.wav("new-person-b.wav", freq=1200)
        retry_audio = self.wav("different-person-c.wav", freq=1700)
        with (
            patch.object(
                identity,
                "identify",
                side_effect=[
                    self._novelty_result(a["id"]),
                    self._novelty_result(a["id"]),
                ],
            ),
            patch.object(
                identity,
                "_novelty_pair_consistency",
                return_value={"consistent": False, "reasons": ["novelty_pair_inconsistent"]},
            ),
        ):
            identity.add_identity_capture(
                attempt["id"],
                first_audio,
                db_path=self.db,
            )
            result = identity.retry_identity_attempt(
                attempt["id"],
                retry_audio,
                db_path=self.db,
            )

        self.assertEqual(identity.ATTEMPT_UNRESOLVED, result["status"])
        self.assertIn("novelty_pair_inconsistent", result["reasons"])
        self.assertNotIn("new_profile_candidate_confirmed", result["reasons"])
