from __future__ import annotations

import hashlib
import json
import re
import unittest
import wave
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ASSET_ROOT = ROOT / "demo_assets" / "baby_audio"
MANIFEST = ASSET_ROOT / "manifest.json"
SHOWCASE_ROOT = ASSET_ROOT / "warning-demo"
SHOWCASE_MANIFEST = SHOWCASE_ROOT / "showcase-manifest.json"


class BabyDemoAssetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        cls.showcase = json.loads(SHOWCASE_MANIFEST.read_text(encoding="utf-8"))

    def test_manifest_is_explicit_about_proxy_identity_and_license(self):
        self.assertEqual(
            self.manifest["identity_grouping_basis"],
            "shared_app_install_uuid_proxy_not_verified_infant",
        )
        self.assertFalse(self.manifest["independent_accuracy_dataset"])
        self.assertEqual(self.manifest["database_license"], "ODbL-1.0")
        self.assertEqual(self.manifest["contents_license"], "DbCL-1.0")
        self.assertTrue((ASSET_ROOT / "LICENSE-DATA.md").is_file())

    def test_three_groups_have_complete_rehearsal_sets(self):
        groups = self.manifest["groups"]
        self.assertEqual([group["label"] for group in groups], ["Baby 1", "Baby 2", "Baby 3"])
        self.assertEqual(len({group["source_app_install_uuid"] for group in groups}), 3)

        all_hashes = set()
        for group in groups:
            records = group["records"]
            self.assertEqual(len(records), 6)
            self.assertEqual(
                [record["demo_role"] for record in records],
                [
                    "enrollment",
                    "enrollment",
                    "enrollment",
                    "held_out_rehearsal_query",
                    "retry",
                    "extra",
                ],
            )
            expected_prefix = group["source_app_install_uuid"].casefold()
            for record in records:
                self.assertTrue(
                    Path(record["source_relative_path"]).name.casefold().startswith(expected_prefix)
                )
                self.assertNotIn(record["sha256"], all_hashes)
                all_hashes.add(record["sha256"])

        self.assertEqual(len(all_hashes), 18)

    def test_every_declared_wav_exists_and_matches_manifest(self):
        declared = []
        for group in self.manifest["groups"]:
            for record in group["records"]:
                path = ASSET_ROOT / record["path"]
                declared.append(path.resolve())
                self.assertTrue(path.is_file(), record["path"])
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), record["sha256"])
                with wave.open(str(path), "rb") as wav:
                    duration = wav.getnframes() / wav.getframerate()
                    self.assertEqual(wav.getnchannels(), record["channels"])
                    self.assertEqual(wav.getframerate(), record["sample_rate_hz"])
                    self.assertAlmostEqual(duration, record["duration_seconds"], places=2)

        for record in self.showcase["assets"]:
            path = SHOWCASE_ROOT / record["path"]
            declared.append(path.resolve())
            self.assertTrue(path.is_file(), record["path"])
            self.assertEqual(
                hashlib.sha256(path.read_bytes()).hexdigest(),
                record["asset_sha256"],
            )
            with wave.open(str(path), "rb") as wav:
                duration = wav.getnframes() / wav.getframerate()
                self.assertEqual(
                    wav.getnchannels(),
                    record["format"]["channels"],
                )
                self.assertEqual(
                    wav.getframerate(),
                    record["format"]["sample_rate_hz"],
                )
                self.assertAlmostEqual(
                    duration,
                    record["format"]["duration_seconds"],
                    places=2,
                )

        for record in self.showcase["supporting_files"]:
            path = SHOWCASE_ROOT / record["path"]
            declared.append(path.resolve())
            self.assertTrue(path.is_file(), record["path"])
            self.assertEqual(
                hashlib.sha256(path.read_bytes()).hexdigest(),
                record["sha256"],
            )
            with wave.open(str(path), "rb") as wav:
                duration = wav.getnframes() / wav.getframerate()
                self.assertEqual(wav.getnchannels(), record["channels"])
                self.assertEqual(wav.getframerate(), record["sample_rate_hz"])
                self.assertAlmostEqual(duration, record["duration_seconds"], places=2)

        curated_group_wavs = sorted(
            path.resolve()
            for group in self.manifest["groups"]
            for path in (ASSET_ROOT / group["directory"]).rglob("*.wav")
        )
        curated_declared = sorted(
            (ASSET_ROOT / record["path"]).resolve()
            for group in self.manifest["groups"]
            for record in group["records"]
        )
        self.assertEqual(curated_declared, curated_group_wavs)

    def test_showcase_contract_describes_current_production_gate(self):
        self.assertEqual(self.showcase["schema_version"], 2)
        gate = self.showcase["production_gate"]
        self.assertEqual(gate["segment_seconds"], 3)
        self.assertEqual(gate["candidate_segments"], 1)
        self.assertEqual(gate["additional_grounded_confirmations"], 5)
        self.assertEqual(gate["required_grounded_segments"], 6)
        self.assertEqual(gate["minimum_segments_before_suggestion"], 7)
        self.assertEqual(gate["minimum_analyzed_audio_seconds"], 20.0)
        self.assertEqual(
            gate["observed_latch_audio_seconds"],
            {"X4": 21, "X7": 30, "X8": 21},
        )
        self.assertTrue(gate["duplicate_guard"]["enabled"])
        self.assertTrue(gate["duplicate_guard"]["exact_source_digest"])
        self.assertTrue(gate["duplicate_guard"]["near_duplicate_signature"])
        self.assertTrue(self.showcase["memory_design"]["synthetic_history"])

    def test_showcase_has_three_current_verified_latching_sources(self):
        records = self.showcase["assets"]
        self.assertEqual([record["order"] for record in records], [1, 2, 3])
        self.assertEqual(
            [Path(record["source_recording"]).name for record in records],
            ["07-X4.wav", "13-X7.wav", "15-X8.wav"],
        )
        self.assertEqual(len({record["source_sha256"] for record in records}), 3)
        self.assertEqual(
            [record["observed_latch_audio_seconds"] for record in records],
            [21, 30, 21],
        )
        for record in records:
            self.assertNotIn("six_second_quiet_probe", record)
            for subtitle_key in ("subtitle", "short_subtitle"):
                subtitle = SHOWCASE_ROOT / record[subtitle_key]
                self.assertTrue(subtitle.is_file(), record[subtitle_key])

        acceptance = self.showcase["production_acceptance"]
        self.assertFalse(acceptance["production_database_changed"])
        result = acceptance["result"]
        self.assertEqual(result["status"], "passed")
        self.assertEqual((result["passed"], result["tested"]), (3, 3))
        self.assertEqual(result["distinct_recommendations"], 3)
        self.assertEqual(
            [item["recommendation"] for item in result["outputs"]],
            [
                "What helped before: offered bottle.",
                "What helped before: held baby upright.",
                "What helped before: turned on white noise.",
            ],
        )
        self.assertEqual(
            [item["processed_segments"] for item in result["outputs"]],
            [7, 10, 7],
        )
        self.assertEqual(
            [item["cry_positive_segments"] for item in result["outputs"]],
            [7, 10, 7],
        )
        self.assertEqual(
            [item["first_cry_audio_seconds"] for item in result["outputs"]],
            [3, 3, 3],
        )
        self.assertEqual(
            [item["latch_audio_seconds"] for item in result["outputs"]],
            [21, 30, 21],
        )
        self.assertEqual(
            [item["action"] for item in result["outputs"]],
            ["offered bottle", "held baby upright", "turned on white noise"],
        )
        for item in result["outputs"]:
            self.assertEqual(item["profile"], "Demo Baby")
            self.assertEqual(item["guidance_status"], "grounded")
            self.assertEqual(item["support_count"], 2)
            self.assertEqual(item["worked_outcomes"], 2)
            self.assertEqual(
                item["basis"],
                [
                    "cry pattern was the strongest available signal",
                    "occurred at a similar time of day",
                ],
            )
            self.assertTrue(item["clean_demo_result"])

    def test_showcase_subtitles_align_suggestions_with_observed_latches(self):
        cases = (
            (
                21.0,
                "What helped before: offered bottle.",
                "captions/01-x4.srt",
                "captions/distinct-output/01-x4-bottle.srt",
            ),
            (
                30.0,
                "What helped before: held baby upright.",
                "captions/02-x7.srt",
                "captions/distinct-output/02-x7-upright.srt",
            ),
            (
                21.0,
                "What helped before: turned on white noise.",
                "captions/03-x8.srt",
                "captions/distinct-output/03-x8-white-noise.srt",
            ),
        )

        def timestamp_seconds(value):
            match = re.fullmatch(
                r"(\d\d):(\d\d):(\d\d),(\d\d\d)",
                value,
            )
            self.assertIsNotNone(match, value)
            hour, minute, second, millisecond = map(int, match.groups())
            self.assertLess(minute, 60)
            self.assertLess(second, 60)
            return hour * 3600 + minute * 60 + second + millisecond / 1000

        for latch, suggestion, *relative_paths in cases:
            for relative_path in relative_paths:
                path = SHOWCASE_ROOT / relative_path
                blocks = re.split(
                    r"\n\s*\n",
                    path.read_text(encoding="utf-8").strip(),
                )
                previous_end = 0.0
                suggestion_starts = []
                for expected_number, block in enumerate(blocks, 1):
                    lines = block.splitlines()
                    self.assertEqual(int(lines[0]), expected_number, path)
                    start_raw, end_raw = lines[1].split(" --> ")
                    start = timestamp_seconds(start_raw)
                    end = timestamp_seconds(end_raw)
                    self.assertGreaterEqual(start, previous_end, path)
                    self.assertGreater(end, start, path)
                    self.assertLessEqual(end, 46.5, path)
                    if suggestion in "\n".join(lines[2:]):
                        suggestion_starts.append(start)
                    previous_end = end
                self.assertEqual(suggestion_starts, [latch], path)


if __name__ == "__main__":
    unittest.main()
