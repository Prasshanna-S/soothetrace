"""Communication Passport export - task 3.2.

These tests exist mostly to pin the HONESTY properties, not the formatting. The failure mode of
this artifact is not looking wrong, it is being believed: a passport gets photographed and
forwarded, so anything that qualifies it has to be inside the document. Every test below that
looks pedantic is guarding one of those qualifications.
"""
import os
import unittest
from tempfile import TemporaryDirectory

from src import passport, store


def _ep(subject, **fields):
    ep = {"subject_id": subject}
    ep.update(fields)
    return ep


class PassportStatusTests(unittest.TestCase):
    def test_a_subject_with_no_recordings_says_so_instead_of_rendering_empty(self):
        with TemporaryDirectory() as d:
            db = os.path.join(d, "p.db")
            store.init_db(db)
            built = passport.build("nobody", db)
            markdown = passport.render_markdown("nobody", db)

        self.assertEqual(passport.STATUS_EMPTY, built["status"])
        self.assertIn("NO USABLE RECORDINGS YET", markdown)
        # The distinction that matters: silence in the record is not a finding.
        self.assertIn("not a finding", markdown.casefold())

    def test_a_thin_record_is_stamped_provisional_rather_than_looking_confident(self):
        with TemporaryDirectory() as d:
            db = os.path.join(d, "p.db")
            store.save_episode(_ep("baby-thin", fingerprint=[0.1] * 87,
                                   interventions=[{"order": 1, "action": "fed"}],
                                   outcome="settled", outcome_src="caregiver",
                                   worked=True), db)
            built = passport.build("baby-thin", db)
            markdown = passport.render_markdown("baby-thin", db)

        self.assertEqual(passport.STATUS_PROVISIONAL, built["status"])
        self.assertIn("PROVISIONAL", markdown)
        self.assertIn("coincidence", markdown.casefold())

    def test_enough_recordings_clears_provisional(self):
        with TemporaryDirectory() as d:
            db = os.path.join(d, "p.db")
            for i in range(passport.MIN_EPISODES_FOR_PASSPORT):
                store.save_episode(_ep("baby-ready", fingerprint=[0.1] * 87,
                                       started_at="2026-07-%02dT19:00:00+00:00" % (i + 1),
                                       interventions=[{"order": 1, "action": "walked her"}],
                                       outcome="settled", outcome_src="caregiver",
                                       worked=True), db)
            built = passport.build("baby-ready", db)
            markdown = passport.render_markdown("baby-ready", db)

        self.assertEqual(passport.STATUS_READY, built["status"])
        self.assertNotIn("PROVISIONAL", markdown)

    def test_an_unfingerprintable_capture_is_not_counted_as_usable(self):
        """A silent or failed capture is stored but cannot be compared.

        Counting it would tell the caregiver she has recordings that retrieval will silently
        refuse to use, and she would have no way to tell which number was lying.
        """
        with TemporaryDirectory() as d:
            db = os.path.join(d, "p.db")
            store.save_episode(_ep("baby-mixed", fingerprint=[0.1] * 87), db)
            store.save_episode(_ep("baby-mixed", fingerprint=None), db)
            built = passport.build("baby-mixed", db)

        self.assertEqual(1, built["episodes"]["usable"])
        self.assertEqual(2, built["episodes"]["total"])


class PassportAttributionTests(unittest.TestCase):
    def test_only_the_final_action_is_credited_with_settling(self):
        with TemporaryDirectory() as d:
            db = os.path.join(d, "p.db")
            store.save_episode(_ep("baby-order", fingerprint=[0.1] * 87,
                                   interventions=[{"order": 1, "action": "checked diaper"},
                                                  {"order": 2, "action": "fed"}],
                                   outcome="feeding settled her",
                                   outcome_src="caregiver", worked=True), db)
            built = passport.build("baby-order", db)

        worked = {t["action"]: t for t in built["what_has_worked"]}
        self.assertEqual(["fed"], list(worked))
        self.assertEqual(1, worked["fed"]["worked_last"])

        tried = {t["action"] for t in built["tried_without_recorded_resolution"]}
        self.assertEqual({"checked diaper"}, tried)

    def test_an_action_with_no_recorded_resolution_is_not_called_ineffective(self):
        with TemporaryDirectory() as d:
            db = os.path.join(d, "p.db")
            store.save_episode(_ep("baby-nores", fingerprint=[0.1] * 87,
                                   interventions=[{"order": 1, "action": "rocked"}],
                                   worked=False), db)
            markdown = passport.render_markdown("baby-nores", db)

        self.assertIn("rocked", markdown)
        self.assertIn("NOT evidence that it does not", markdown)

    def test_the_document_never_asserts_a_cause_or_gives_an_instruction(self):
        with TemporaryDirectory() as d:
            db = os.path.join(d, "p.db")
            for i in range(3):
                store.save_episode(_ep("baby-claims", fingerprint=[0.1] * 87,
                                       interventions=[{"order": 1, "action": "fed"}],
                                       outcome="settled", outcome_src="caregiver",
                                       worked=True), db)
            markdown = passport.render_markdown("baby-claims", db)

        low = markdown.casefold()
        self.assertIn("none of it is a cause", low)
        self.assertIn("counts, not instructions", low)
        # Cause language that must never be generated about a pre-verbal subject. Only
        # phrasings that cannot occur inside a DENIAL are listed: "diagnosis" and
        # "recommendation" both appear legitimately in the limits section, which exists
        # precisely to say the document is neither of those.
        for banned in ("was hungry", "is hungry", "because the baby", "because she",
                       "because he", "you should", "try ", "make sure"):
            self.assertNotIn(banned, low, "passport must not contain %r" % banned)

    def test_no_comparison_against_population_norms_is_made(self):
        with TemporaryDirectory() as d:
            db = os.path.join(d, "p.db")
            store.save_episode(_ep("baby-norm", fingerprint=[0.1] * 87), db)
            markdown = passport.render_markdown("baby-norm", db)

        self.assertIn("no comparison", markdown.casefold())
        for banned in ("more than normal", "above average", "percentile"):
            self.assertNotIn(banned, markdown.casefold())


class PassportProvenanceTests(unittest.TestCase):
    def test_seeded_data_is_stamped_at_the_top_not_buried(self):
        with TemporaryDirectory() as d:
            db = os.path.join(d, "p.db")
            store.save_episode(_ep("baby-seed", fingerprint=[0.1] * 87,
                                   interventions=[{"order": 1, "action": "fed"}],
                                   outcome="settled", outcome_src="seed", worked=True), db)
            built = passport.build("baby-seed", db)
            markdown = passport.render_markdown("baby-seed", db)

        self.assertTrue(built["synthetic"])
        head = markdown.split("## ")[0]
        self.assertIn("SYNTHETIC DEMO DATA", head)
        self.assertIn("Do not use it for a real person", head)

    def test_an_inferred_outcome_is_labelled_as_weaker_than_a_reported_one(self):
        with TemporaryDirectory() as d:
            db = os.path.join(d, "p.db")
            store.save_episode(_ep("baby-inf", fingerprint=[0.1] * 87,
                                   interventions=[{"order": 1, "action": "fed"}],
                                   outcome="stopped", outcome_src="inferred", worked=True), db)
            markdown = passport.render_markdown("baby-inf", db)

        self.assertIn("inferred from the recording", markdown)
        self.assertIn("weaker evidence", markdown)


class PassportTimeOfDayTests(unittest.TestCase):
    def test_the_device_local_hour_wins_over_the_timestamp_timezone(self):
        """context.hour_local is what the capturing device recorded in the room.

        started_at can carry a different timezone, and a passport that calls a morning an
        evening is worse than one that says nothing about time at all.
        """
        with TemporaryDirectory() as d:
            db = os.path.join(d, "p.db")
            store.save_episode(_ep("baby-tz", fingerprint=[0.1] * 87,
                                   started_at="2026-07-01T02:00:00+00:00",
                                   context={"hour_local": 19}), db)
            built = passport.build("baby-tz", db)

        self.assertEqual([("evening", 1)], built["when_recorded"])

    def test_time_of_day_is_reported_without_a_causal_claim(self):
        with TemporaryDirectory() as d:
            db = os.path.join(d, "p.db")
            store.save_episode(_ep("baby-tod", fingerprint=[0.1] * 87,
                                   context={"hour_local": 20}), db)
            markdown = passport.render_markdown("baby-tod", db)

        self.assertIn("No claim is made that the time causes anything", markdown)


class PassportOutputHygieneTests(unittest.TestCase):
    def test_the_rendered_document_is_plain_ascii(self):
        """The owner requires plain punctuation, and this document gets pasted everywhere."""
        with TemporaryDirectory() as d:
            db = os.path.join(d, "p.db")
            store.save_episode(_ep("baby-ascii", fingerprint=[0.1] * 87,
                                   interventions=[{"order": 1, "action": "fed"}],
                                   outcome="settled", outcome_src="seed", worked=True,
                                   context={"hour_local": 19}), db)
            markdown = passport.render_markdown("baby-ascii", db)

        offenders = sorted({c for c in markdown if ord(c) > 127})
        self.assertEqual([], offenders, "non-ASCII in the passport: %r" % offenders)

    def test_a_prebuilt_passport_is_not_silently_rebuilt(self):
        """Two renders in one session must not be able to disagree."""
        with TemporaryDirectory() as d:
            db = os.path.join(d, "p.db")
            store.save_episode(_ep("baby-reuse", fingerprint=[0.1] * 87), db)
            built = passport.build("baby-reuse", db)
            built["subject_id"] = "SENTINEL"
            markdown = passport.render_markdown("baby-reuse", db, passport=built)

        self.assertIn("SENTINEL", markdown)


if __name__ == "__main__":
    unittest.main()
