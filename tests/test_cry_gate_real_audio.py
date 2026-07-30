import csv
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from src import cry_gate


ROOT = Path(__file__).resolve().parents[1]
BABY_ROOT = ROOT / "demo_assets" / "baby_audio"
ADULT_ROOT = ROOT / "demo_assets" / "human_audio"
RUN_MODEL_TESTS = os.environ.get("IM_RUN_CRY_MODEL_TESTS") == "1"


@unittest.skipUnless(
    RUN_MODEL_TESTS,
    "set IM_RUN_CRY_MODEL_TESTS=1 to run the cached AST model",
)
class CryGateRealAudioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not cry_gate.warm():
            raise AssertionError("cached infant cry model is unavailable")
        cls.tempdir = tempfile.TemporaryDirectory()
        cls.canonical_root = Path(cls.tempdir.name)

    @classmethod
    def tearDownClass(cls):
        cls.tempdir.cleanup()

    def _canonical(self, source: Path) -> str:
        relative = source.relative_to(source.parents[2])
        target = self.canonical_root / relative.with_suffix(".wav")
        if target.is_file():
            return str(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        completed = subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-y",
                "-i",
                str(source),
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-c:a",
                "pcm_s16le",
                str(target),
            ],
            capture_output=True,
            timeout=180,
            check=False,
        )
        self.assertEqual(
            0,
            completed.returncode,
            completed.stderr.decode("utf-8", "replace"),
        )
        return str(target)

    def _classify_all(self, paths: list[Path]) -> list[tuple[Path, str]]:
        return [
            (path, cry_gate.classify(self._canonical(path))["status"])
            for path in paths
        ]

    def _assert_confusion(
        self,
        positives: list[Path],
        negatives: list[Path],
        minimum_true_positives: int,
        expected_false_positives: int = 0,
    ) -> None:
        positive_results = self._classify_all(positives)
        negative_results = self._classify_all(negatives)
        true_positives = sum(
            status == "infant_cry_detected"
            for _, status in positive_results
        )
        false_positives = sum(
            status == "infant_cry_detected"
            for _, status in negative_results
        )
        passed = (
            true_positives >= minimum_true_positives
            and false_positives == expected_false_positives
        )
        if not passed:
            print(
                "\ncry gate confusion table\n"
                f"  true positives: {true_positives} of {len(positives)}\n"
                f"  false negatives: {len(positives) - true_positives} "
                f"of {len(positives)}\n"
                f"  false positives: {false_positives} of {len(negatives)}\n"
                f"  true negatives: {len(negatives) - false_positives} "
                f"of {len(negatives)}"
            )
            for path, status in positive_results + negative_results:
                print(f"  {path.name}: {status}")
        self.assertGreaterEqual(true_positives, minimum_true_positives)
        self.assertEqual(expected_false_positives, false_positives)

    def test_planned_baby_one_query_is_strong(self):
        status = cry_gate.classify(
            self._canonical(BABY_ROOT / "baby-1" / "baby-1-04.wav")
        )["status"]
        self.assertEqual("infant_cry_detected", status)

    def test_adult_imitation_is_not_strong(self):
        status = cry_gate.classify(
            self._canonical(ADULT_ROOT / "prasshanna-01.wav")
        )["status"]
        self.assertNotEqual("infant_cry_detected", status)

    def test_checked_in_fixture_confusion_minimums(self):
        infant_paths = sorted(BABY_ROOT.glob("baby-*/*.wav"))
        manifest = json.loads(
            (ADULT_ROOT / "manifest.json").read_text(encoding="utf-8")
        )
        adult_paths = [
            ADULT_ROOT / filename
            for profile in manifest["profiles"]
            for filename in profile["files"]
        ]

        self.assertEqual(18, len(infant_paths))
        self.assertEqual(10, len(adult_paths))
        self._assert_confusion(infant_paths, adult_paths, 14)

    def test_optional_esc50_slice_confusion_minimums(self):
        esc_root_value = os.environ.get("IM_ESC50_DIR")
        if not esc_root_value:
            self.skipTest("set IM_ESC50_DIR to the separately downloaded ESC-50 root")
        esc_root = Path(esc_root_value)
        metadata = esc_root / "meta" / "esc50.csv"
        audio_root = esc_root / "audio"
        if not metadata.is_file() or not audio_root.is_dir():
            self.skipTest("IM_ESC50_DIR does not contain an ESC-50 checkout")

        by_category: dict[str, list[Path]] = {}
        with metadata.open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                by_category.setdefault(row["category"], []).append(
                    audio_root / row["filename"]
                )

        infant_paths = sorted(by_category.pop("crying_baby"))
        negative_paths = [
            path
            for category in sorted(by_category)
            for path in sorted(by_category[category])[:5]
        ]
        self.assertEqual(40, len(infant_paths))
        self.assertEqual(245, len(negative_paths))
        self._assert_confusion(infant_paths, negative_paths, 40)


if __name__ == "__main__":
    unittest.main()
