import os
import sqlite3
import unittest
from tempfile import TemporaryDirectory
from unittest.mock import patch

from src import store


class DeleteEpisodeTests(unittest.TestCase):
    def test_delete_removes_stale_subject_baseline_below_two_episodes(self):
        with TemporaryDirectory() as directory:
            db_path = os.path.join(directory, "episodes.db")
            first_audio = os.path.join(directory, "first.wav")
            second_audio = os.path.join(directory, "second.wav")
            with open(first_audio, "wb") as audio:
                audio.write(b"first")
            with open(second_audio, "wb") as audio:
                audio.write(b"second")

            with (
                patch.object(store.config, "DB_PATH", db_path),
                patch.object(store.config, "AUDIO_DIR", directory),
            ):
                first_id = store.save_episode(
                    {
                        "subject_id": "baby-delete",
                        "audio_path": first_audio,
                        "fingerprint": [0.0] * 87,
                    }
                )
                store.save_episode(
                    {
                        "subject_id": "baby-delete",
                        "audio_path": second_audio,
                        "fingerprint": [1.0] * 87,
                    }
                )
                self.assertEqual(
                    store.get_baseline("baby-delete")["n"],
                    2,
                )

                deleted = store.delete_episode(first_id)

                self.assertTrue(deleted)
                self.assertFalse(os.path.exists(first_audio))
                self.assertEqual(len(store.list_episodes("baby-delete")), 1)
                self.assertIsNone(store.get_baseline("baby-delete"))


class CorruptRowTests(unittest.TestCase):
    def test_corrupt_fingerprint_blob_degrades_to_none(self):
        with TemporaryDirectory() as directory:
            db_path = os.path.join(directory, "episodes.db")
            store.init_db(db_path)
            con = sqlite3.connect(db_path)
            episode_id = con.execute(
                "INSERT INTO episode "
                "(subject_id,started_at,fingerprint,interventions,context) "
                "VALUES (?,?,?,?,?)",
                ("corrupt", "invalid", b"x", "{bad", "{bad"),
            ).lastrowid
            con.commit()
            con.close()

            episode = store.get_episode(episode_id, db_path)

            self.assertIsNotNone(episode)
            self.assertIsNone(episode["fingerprint"])
            self.assertEqual(episode["interventions"], [])
            self.assertEqual(episode["context"], {})


if __name__ == "__main__":
    unittest.main()
