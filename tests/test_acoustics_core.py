"""Tests for acoustics workstream-owned modules: fingerprint, store, retrieve, diary.

Run: .venv/bin/python -m unittest discover -s tests -v

The most important test in this file is
`TestNormalizationInvariant.test_distinct_vectors_do_not_all_match`. It guards the
regression that would silently destroy the product: on RAW fingerprints, a DIFFERENT baby
scored +0.9999 while a file matched itself at +0.9915 (docs/FINDINGS.md §5). If normalization
is ever bypassed, everything matches everything, retrieval returns the same answer forever,
and the app still LOOKS like it works. That is the failure mode with no visible symptom.
"""
from __future__ import annotations

import math
import os
import struct
import sys
import tempfile
import unittest
import wave

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

import config          # noqa: E402
import diary           # noqa: E402
import fingerprint     # noqa: E402
import retrieve        # noqa: E402
import store           # noqa: E402


def write_tone_wav(path: str, freq: float = 400.0, seconds: float = 2.0,
                   amp: float = 0.3, sr: int = 16000) -> str:
    """Write a mono 16-bit tone. stdlib only - no soundfile dependency in tests."""
    n = int(seconds * sr)
    frames = bytearray()
    for i in range(n):
        v = int(amp * 32767 * math.sin(2 * math.pi * freq * i / sr))
        frames += struct.pack("<h", v)
    with wave.open(path, "wb") as fh:
        fh.setnchannels(1)
        fh.setsampwidth(2)
        fh.setframerate(sr)
        fh.writeframes(bytes(frames))
    return path


class TempDB(unittest.TestCase):
    """Every test gets an isolated database file."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self._tmp.name, "test.db")
        store.init_db(self.db)

    def tearDown(self):
        self._tmp.cleanup()

    def mk_fp(self, seed: float) -> list[float]:
        """A deterministic, distinctive fingerprint. Not audio-derived - these tests
        exercise storage and retrieval logic, not feature extraction."""
        return [math.sin(seed * (i + 1)) * (1 + seed) for i in range(fingerprint.DIM)]

    def add(self, subject="s1", fp=None, worked=None, ivs=None, started_at=None,
            outcome=None, outcome_src=None, duration_s=30.0):
        return store.save_episode({
            "subject_id": subject,
            "started_at": started_at or "2026-07-01T19:20:00-04:00",
            "duration_s": duration_s,
            "fingerprint": fp if fp is not None else self.mk_fp(0.1),
            "interventions": ivs or [],
            "outcome": outcome,
            "outcome_src": outcome_src,
            "worked": worked,
        }, self.db)


# --------------------------------------------------------------- fingerprint

class TestFingerprint(unittest.TestCase):

    def test_dim_is_87(self):
        """87 is load-bearing: the measured results in FINDINGS.md describe this layout."""
        self.assertEqual(fingerprint.DIM, 87)

    def test_compute_returns_dim_floats_on_real_audio(self):
        with tempfile.TemporaryDirectory() as d:
            p = write_tone_wav(os.path.join(d, "tone.wav"))
            fp = fingerprint.compute(p)
            self.assertIsNotNone(fp, "tone at -13dB should be loud enough to fingerprint")
            self.assertEqual(len(fp), fingerprint.DIM)
            self.assertTrue(all(isinstance(x, float) for x in fp))
            self.assertTrue(all(math.isfinite(x) for x in fp))

    def test_windowed_matches_dim(self):
        with tempfile.TemporaryDirectory() as d:
            p = write_tone_wav(os.path.join(d, "tone.wav"), seconds=5.0)
            fp = fingerprint.compute_windowed(p)
            self.assertIsNotNone(fp)
            self.assertEqual(len(fp), fingerprint.DIM)

    def test_missing_and_silent_audio_return_none_not_raise(self):
        self.assertIsNone(fingerprint.compute("/nonexistent/nope.wav"))
        self.assertIsNone(fingerprint.load_audio("/nonexistent/nope.wav"))
        with tempfile.TemporaryDirectory() as d:
            silent = write_tone_wav(os.path.join(d, "s.wav"), amp=0.0)
            self.assertIsNone(fingerprint.compute(silent),
                              "silence has no voiced frames -> None, not a zero vector")
            tiny = write_tone_wav(os.path.join(d, "t.wav"), seconds=0.1)
            self.assertIsNone(fingerprint.compute(tiny))

    def test_build_context_hour_and_gap(self):
        ctx = fingerprint.build_context("2026-07-01T19:20:00-04:00",
                                        "2026-07-01T17:20:00-04:00", 42)
        self.assertEqual(ctx["hour_local"], 19)
        self.assertAlmostEqual(ctx["minutes_since_prev_episode"], 120.0, places=3)
        self.assertEqual(ctx["subject_age_days"], 42)

    def test_build_context_tolerates_garbage(self):
        ctx = fingerprint.build_context("not-a-date", None, None)
        self.assertIsNone(ctx["hour_local"])
        self.assertIsNone(ctx["minutes_since_prev_episode"])


# --------------------------------------------------------------------- store

class TestStore(TempDB):

    def test_roundtrip_preserves_fingerprint_and_json(self):
        fp = self.mk_fp(0.42)
        ivs = [{"order": 1, "action": "offered bottle", "evidence": "let me get your bottle"}]
        eid = self.add(fp=fp, ivs=ivs, worked=True, outcome="fed him",
                       outcome_src="caregiver")
        self.assertGreater(eid, 0)
        ep = store.get_episode(eid, self.db)
        self.assertEqual(len(ep["fingerprint"]), fingerprint.DIM)
        for a, b in zip(ep["fingerprint"], fp):
            self.assertAlmostEqual(a, b, places=5)
        self.assertEqual(ep["interventions"], ivs)
        self.assertIs(ep["worked"], True)

    def test_worked_none_survives_as_none(self):
        """None must not become False. The exhausted-parent path is None, and
        LIABILITY §5's safety check depends on telling them apart."""
        eid = self.add(worked=None)
        self.assertIsNone(store.get_episode(eid, self.db)["worked"])

    def test_worked_false_survives_as_false(self):
        eid = self.add(worked=False)
        self.assertIs(store.get_episode(eid, self.db)["worked"], False)

    def test_list_is_newest_first(self):
        self.add(started_at="2026-07-01T19:00:00-04:00")
        self.add(started_at="2026-07-03T19:00:00-04:00")
        self.add(started_at="2026-07-02T19:00:00-04:00")
        got = [e["started_at"][:10] for e in store.list_episodes("s1", self.db)]
        self.assertEqual(got, ["2026-07-03", "2026-07-02", "2026-07-01"])

    def test_update_episode_patches_and_ignores_unknown_keys(self):
        eid = self.add()
        store.update_episode(eid, self.db, outcome="rocking worked", worked=True,
                             nonsense_key="ignored")
        ep = store.get_episode(eid, self.db)
        self.assertEqual(ep["outcome"], "rocking worked")
        self.assertIs(ep["worked"], True)

    def test_bad_input_returns_zero_not_raise(self):
        self.assertEqual(store.save_episode({}, self.db), 0)
        self.assertEqual(store.save_episode({"started_at": "x"}, self.db), 0)
        self.assertIsNone(store.get_episode(999999, self.db))
        self.assertEqual(store.list_episodes("nobody", self.db), [])

    def test_delete_removes_row_and_refreshes_baseline(self):
        a = self.add(fp=self.mk_fp(0.1))
        self.add(fp=self.mk_fp(0.9))
        self.assertIsNotNone(store.get_baseline("s1", self.db))
        self.assertTrue(store.delete_episode(a, self.db))
        self.assertIsNone(store.get_episode(a, self.db))
        self.assertEqual(len(store.list_episodes("s1", self.db)), 1)
        # dropping below 2 fingerprints must clear the now-stale subject baseline
        self.assertIsNone(store.get_baseline("s1", self.db),
                          "stale per-subject baseline must not survive")

    def test_delete_never_touches_files_outside_audio_dir(self):
        with tempfile.TemporaryDirectory() as d:
            outside = write_tone_wav(os.path.join(d, "corpus.wav"))
            eid = store.save_episode({"subject_id": "s1", "audio_path": outside,
                                      "fingerprint": self.mk_fp(0.2)}, self.db)
            store.delete_episode(eid, self.db)
            self.assertTrue(os.path.exists(outside),
                            "corpus/source audio outside AUDIO_DIR must never be deleted")


# ------------------------------------------------------------------ retrieve

class TestRetrieveGating(TempDB):

    def test_returns_empty_below_min_episodes(self):
        for i in range(retrieve.MIN_EPISODES_FOR_MATCH - 1):
            self.add(fp=self.mk_fp(0.1 * (i + 1)))
        store.save_baseline(config.POPULATION_KEY, [0.0] * fingerprint.DIM,
                            [1.0] * fingerprint.DIM, 100, self.db)
        self.assertEqual(
            retrieve.find_similar("s1", self.mk_fp(0.15), db_path=self.db), [],
            "must refuse to guess below MIN_EPISODES_FOR_MATCH")

    def test_returns_empty_with_no_baseline_at_all(self):
        """No baseline => no safe comparison. Raw cosine would score ~0.99 for
        everything (FINDINGS §5), so [] is the only honest answer."""
        for i in range(6):
            self.add(fp=self.mk_fp(0.1 * (i + 1)))
        con_rows = store.get_baseline(config.POPULATION_KEY, self.db)
        self.assertIsNone(con_rows)
        # a per-subject fallback baseline does exist after >=2 inserts; remove it
        import sqlite3
        con = sqlite3.connect(self.db)
        con.execute("DELETE FROM baseline")
        con.commit()
        con.close()
        self.assertEqual(retrieve.find_similar("s1", self.mk_fp(0.15), db_path=self.db), [])

    def test_excludes_the_query_episode(self):
        ids = [self.add(fp=self.mk_fp(0.1 * (i + 1))) for i in range(6)]
        store.save_baseline(config.POPULATION_KEY, [0.0] * fingerprint.DIM,
                            [1.0] * fingerprint.DIM, 100, self.db)
        q = store.get_episode(ids[0], self.db)
        got = retrieve.find_similar("s1", q["fingerprint"], k=5,
                                    exclude_episode_id=ids[0], db_path=self.db)
        self.assertNotIn(ids[0], [m["episode_id"] for m in got],
                         "an episode must never be its own memory")

    def test_bad_input_is_empty_not_raise(self):
        self.assertEqual(retrieve.find_similar("", [1.0], db_path=self.db), [])
        self.assertEqual(retrieve.find_similar("s1", [], db_path=self.db), [])
        self.assertEqual(retrieve.find_similar("s1", [1.0, 2.0], db_path=self.db), [],
                         "wrong-length fingerprint must be rejected, not padded")

    def test_episode_count_matches_the_retrieval_gate(self):
        """episode_count drives the 'only your Nth recording' message, so it must count
        the same episodes find_similar can actually use. Counting un-fingerprintable
        episodes would tell the caregiver she has 5 recordings while retrieval refuses."""
        self.add(fp=self.mk_fp(0.1))
        self.add(fp=self.mk_fp(0.2))
        store.save_episode({"subject_id": "s1", "fingerprint": None}, self.db)
        self.assertEqual(retrieve.episode_count("s1", self.db), 2)


class TestNormalizationInvariant(TempDB):

    def test_distinct_vectors_do_not_all_match(self):
        """THE regression guard. See module docstring.

        Six deliberately dissimilar fingerprints. If normalization is bypassed, cosine on
        raw vectors drives everything to ~0.99 and every band becomes 'strong'. A product
        that always answers 'strong' looks like it is working while being useless.
        """
        for i in range(6):
            self.add(fp=self.mk_fp(0.3 * (i + 1)))
        store.save_baseline(config.POPULATION_KEY, [0.0] * fingerprint.DIM,
                            [1.0] * fingerprint.DIM, 100, self.db)
        got = retrieve.find_similar("s1", self.mk_fp(5.5), k=6, db_path=self.db)
        self.assertTrue(got)
        bands = [m["band"] for m in got]
        self.assertLess(bands.count("strong"), len(bands),
                        f"every band came back strong -> normalization bypassed: {bands}")
        sims = [m["similarity"] for m in got]
        self.assertGreater(max(sims) - min(sims), 1e-3,
                           f"similarities are indistinguishable, raw-cosine smell: {sims}")

    def test_similarity_never_reaches_a_band_of_none_only(self):
        """Sanity: a near-duplicate of a stored episode should out-rank the others."""
        target = self.mk_fp(0.7)
        self.add(fp=target)
        for i in range(5):
            self.add(fp=self.mk_fp(3.0 + i))
        store.save_baseline(config.POPULATION_KEY, [0.0] * fingerprint.DIM,
                            [1.0] * fingerprint.DIM, 100, self.db)
        got = retrieve.find_similar("s1", [x * 1.001 for x in target], k=6, db_path=self.db)
        self.assertTrue(got)
        self.assertGreater(got[0]["similarity"], got[-1]["similarity"],
                           "the near-duplicate must rank first")


class TestInterventionTally(TempDB):

    def test_unresolved_episodes_never_credit_a_success(self):
        """Guards bug 2.11: 'nothing worked' must not inflate the T2 payload."""
        ivs = [{"order": 1, "action": "rocking", "evidence": "let me rock you"}]
        for _ in range(5):
            self.add(ivs=ivs, worked=False)
        tally = retrieve.intervention_tally("s1", self.db)
        self.assertEqual(len(tally), 1)
        self.assertEqual(tally[0]["tried"], 5)
        self.assertEqual(tally[0]["worked"], 0)

    def test_worked_none_is_not_counted_as_success(self):
        ivs = [{"order": 1, "action": "rocking", "evidence": "rock"}]
        for _ in range(3):
            self.add(ivs=ivs, worked=None)
        self.assertEqual(retrieve.intervention_tally("s1", self.db)[0]["worked"], 0)

    def test_last_intervention_attribution(self):
        """The caregiver tries things in sequence and STOPS when one works, so the final
        action in a resolved episode is the probable cause. Crediting all of them dilutes
        the signal that is our headline longitudinal claim."""
        ivs = [
            {"order": 1, "action": "checked diaper", "evidence": "check your diaper"},
            {"order": 2, "action": "fed", "evidence": "let me feed you"},
        ]
        for _ in range(4):
            self.add(ivs=ivs, worked=True)
        by = {t["action"]: t for t in retrieve.intervention_tally("s1", self.db)}
        self.assertEqual(by["fed"]["worked_last"], 4)
        self.assertEqual(by["checked diaper"]["worked_last"], 0,
                         "an action tried and then followed by another did not resolve it")
        self.assertEqual(by["fed"]["worked"], 4)
        self.assertEqual(by["checked diaper"]["worked"], 4)


# --------------------------------------------------------------------- diary

class TestDiary(TempDB):

    def test_empty_subject_does_not_crash(self):
        out = diary.render_markdown("nobody", self.db)
        self.assertIn("No episodes recorded yet", out)

    def test_seed_data_is_flagged_as_synthetic(self):
        self.add(outcome="fed him", outcome_src="seed", worked=True)
        out = diary.render_markdown("s1", self.db)
        self.assertIn("synthetic", out.lower(),
                      "LIABILITY §7: seeded data must never read as a real record")

    def test_no_verdict_against_population_norms(self):
        """LIABILITY §1: showing norms is context; comparing to them is a disease claim."""
        self.add(worked=True, duration_s=600.0)
        out = diary.render_markdown("s1", self.db).lower()
        for banned in ("more than normal", "above average", "abnormal", "excessive"):
            self.assertNotIn(banned, out)

    def test_daily_and_hourly_summaries(self):
        self.add(started_at="2026-07-01T19:20:00-04:00", duration_s=120.0, worked=True)
        self.add(started_at="2026-07-01T22:00:00-04:00", duration_s=60.0, worked=False)
        self.add(started_at="2026-07-02T19:30:00-04:00", duration_s=90.0, worked=None)
        days = diary.daily_summary("s1", self.db)
        self.assertEqual(len(days), 2)
        self.assertEqual(days[0]["episodes"], 2)
        self.assertEqual(days[0]["resolved"], 1)
        self.assertEqual(days[0]["unresolved"], 1)
        self.assertAlmostEqual(days[0]["total_minutes"], 3.0, places=3)
        # worked=None counts as neither -> the honest treatment of an unlabelled episode
        self.assertEqual(days[1]["resolved"], 0)
        self.assertEqual(days[1]["unresolved"], 0)
        hours = diary.hourly_distribution("s1", self.db)
        self.assertEqual(len(hours), 24)
        self.assertEqual(hours[19], 2)
        self.assertEqual(hours[22], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
