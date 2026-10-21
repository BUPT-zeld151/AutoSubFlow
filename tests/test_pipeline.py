"""Synthetic recovery and failure checks; no media tools or models are called."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "dsh/autosubflow/scripts"))
spec = importlib.util.spec_from_file_location(
    "pipeline", ROOT / "dsh/autosubflow/scripts/pipeline_ctl.py"
)
pipeline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pipeline)
sys.path.pop(0)


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.tmp.name)
        # Synthetic placeholder, never passed to a media decoder.
        (self.workspace / "sample.mp4").write_bytes(b"synthetic test fixture")

    def tearDown(self):
        self.tmp.cleanup()

    def test_units_cover_duration_without_gaps(self):
        result = pipeline.init(self.workspace, None, 721000)
        self.assertEqual(result["unit_count"], 3)
        manifest = json.loads((self.workspace / ".subtitle-pipeline/manifest.json").read_text())
        self.assertEqual(
            [(u["start_ms"], u["end_ms"]) for u in manifest["units"]],
            [(0, 360000), (360000, 720000), (720000, 721000)],
        )

    def test_reinitialization_preserves_checkpoint(self):
        pipeline.init(self.workspace, None, 721000)
        path = self.workspace / ".subtitle-pipeline/manifest.json"
        before = path.read_bytes()
        result = pipeline.init(self.workspace, None, 1000)
        self.assertTrue(result["already_initialized"])
        self.assertEqual(path.read_bytes(), before)

    def test_missing_evidence_cannot_pass_gate(self):
        pipeline.init(self.workspace, None, 1000)
        for phase in (1, 2, 3):
            with self.subTest(phase=phase):
                self.assertFalse(pipeline.phase_check(self.workspace, phase)["pass"])

    def test_ambiguous_video_requires_explicit_choice(self):
        (self.workspace / "second.mkv").write_bytes(b"synthetic")
        with self.assertRaises(ValueError):
            pipeline.init(self.workspace, None, 1000)


if __name__ == "__main__":
    unittest.main()
