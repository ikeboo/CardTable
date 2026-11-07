"""Optional integration check requiring the local ML example and its weights."""

import importlib.util
import json
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path


class MLAppMemoryTest(unittest.TestCase):
    @unittest.skipUnless(sys.platform == "darwin", "Apple Silicon regression")
    def test_changing_frames_do_not_accumulate_native_inference_memory(self):
        root = Path(__file__).resolve().parents[1]
        example = root / "examples" / "ml_app"
        required = (
            "zipdepth.py",
            "face_landmark_detector.py",
            "weights/zipdepth_fp16_opset17.onnx",
            "weights/face_detector.onnx",
            "weights/face_detector.data",
            "weights/face_landmark_detector.onnx",
            "weights/face_landmark_detector.data",
        )
        if not all((example / name).is_file() for name in required):
            self.skipTest("local ML example and weights are not installed")
        if importlib.util.find_spec("onnxruntime") is None:
            self.skipTest("onnxruntime is not installed")

        # Isolate ORT's native caches from other tests. Identical frames hide
        # the KleidiAI bug: the cache key includes the input tensor's contents.
        script = textwrap.dedent("""
            import json
            import os
            import sys
            import numpy as np
            from cardtable.widgets._process_usage import _read_process

            sys.path.insert(0, sys.argv[1])
            from zipdepth import ZipDepth
            from face_landmark_detector import FaceLandmarkDetector

            depth = ZipDepth()
            face = FaceLandmarkDetector()
            rng = np.random.default_rng(42)
            readings = []
            for i in range(200):
                frame = rng.integers(0, 256, (480, 640, 3), dtype=np.uint8)
                face.infer_visualize(frame)
                depth.infer_visualize(frame)
                if i >= 39 and (i + 1) % 40 == 0:
                    readings.append(_read_process(os.getpid())[1])
            print(json.dumps(readings))
        """)
        result = subprocess.run(
            [sys.executable, "-c", script, str(example)],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=90,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        readings = json.loads(result.stdout)
        self.assertLess(
            max(readings[1:]) - readings[0],
            64 * 1024**2,
            f"native RSS kept growing after warmup: {readings}",
        )
