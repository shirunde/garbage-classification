import contextlib
import io
import json
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from control import poses
from control.fixed_sort import OBSERVATION_POSE
from shared.schemas import DetectResult
from scripts import run_fixed_sort as cli


class FixedSortCliTests(unittest.TestCase):
    def run_entry(self, args, classes=None, camera_open=True, fail_grasp=False):
        calls = []
        classes = classes or ["other"] * 5
        camera = types.SimpleNamespace(
            set=lambda *a: None,
            isOpened=lambda: camera_open,
            read=lambda: (True, types.SimpleNamespace(shape=(480, 640, 3))),
            release=lambda: calls.append("camera_released"),
        )
        cv2 = types.SimpleNamespace(
            VideoCapture=lambda *a: camera, CAP_V4L2=1, CAP_PROP_FRAME_WIDTH=2,
            CAP_PROP_FRAME_HEIGHT=3, CAP_PROP_BUFFERSIZE=4,
        )

        class Detector:
            def __init__(self, model_path, frame_source):
                self.source = frame_source
                self.model_path = Path("model.om")
                self.items = iter(classes)
            def detect(self):
                self.source()
                cls = next(self.items)
                return None if cls is None else DetectResult(cls, 300, 400, .9, 1)
            def close(self):
                calls.append("detector_closed")

        class Arm:
            def __init__(self):
                calls.append("arm_loaded")
            def _move(self, pose, duration):
                calls.append(("move", list(pose)))
            def grasp(self, target):
                calls.append(("grasp", target.cls, target.u, target.v))
                if fail_grasp:
                    raise RuntimeError("I2C failed")
                return True

        detector_module = types.ModuleType("vision.detector")
        detector_module.AscendDetector = Detector
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(cli, "ROOT", Path(folder)), \
                 patch.dict("sys.modules", {"cv2": cv2, "vision.detector": detector_module}), \
                 patch("control.arm.BoardArm", Arm), \
                 contextlib.redirect_stdout(io.StringIO()), \
                 contextlib.redirect_stderr(io.StringIO()):
                code = cli.main(args)
            record = json.loads(next((Path(folder)/"records").glob("*.json")).read_text(encoding="utf-8"))
        return code, calls, record

    def test_read_only_default_never_loads_arm(self):
        code, calls, record = self.run_entry([])
        self.assertEqual(code, 0)
        self.assertNotIn("arm_loaded", calls)
        self.assertEqual(record["drop_color"], "yellow")
        self.assertEqual(record["status"], "dry_run")
        self.assertFalse(record["command_sequence_completed"])
        self.assertIn("camera_released", calls)
        self.assertIn("detector_closed", calls)

    def test_execute_selects_model_category_and_completes_one_cycle(self):
        code, calls, record = self.run_entry(["--execute"], ["kitchen"]*5)
        self.assertEqual(code, 0)
        self.assertEqual(calls[:4], [
            "arm_loaded", ("move", poses.TOP), ("move", OBSERVATION_POSE),
            ("grasp", "kitchen", 320.0, 240.0),
        ])
        self.assertEqual(calls[4], ("move", OBSERVATION_POSE))
        self.assertEqual(record["drop_color"], "green")
        self.assertTrue(record["command_sequence_completed"])
        self.assertIsNone(record["physical_success_confirmed"])

    def test_conflicting_recognition_never_grasps(self):
        code, calls, record = self.run_entry(["--execute"], ["other"]*4+["recyclable"])
        self.assertEqual(code, 2)
        self.assertFalse(any(isinstance(x, tuple) and x[0]=="grasp" for x in calls))
        self.assertEqual(len(record["observations"]), 5)
        self.assertEqual(record["status"], "stopped")

    def test_camera_failure_prevents_arm_initialization(self):
        code, calls, record = self.run_entry(["--execute"], camera_open=False)
        self.assertEqual(code, 2)
        self.assertNotIn("arm_loaded", calls)
        self.assertIn("camera_released", calls)
        self.assertFalse(record["command_sequence_completed"])

    def test_motion_error_is_logged_without_retry_or_return_move(self):
        code, calls, record = self.run_entry(["--execute"], fail_grasp=True)
        self.assertEqual(code, 2)
        self.assertEqual(sum(isinstance(x, tuple) and x[0]=="grasp" for x in calls), 1)
        self.assertEqual(sum(isinstance(x, tuple) and x[0]=="move" for x in calls), 2)
        self.assertEqual(record["status"], "stopped")
        self.assertFalse(record["command_sequence_completed"])
        self.assertIn("detector_closed", calls)
        self.assertIn("camera_released", calls)

    def test_still_image_cannot_enable_motion(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as caught:
                cli.main(["--execute", "--image", "test.jpg"])
        self.assertEqual(caught.exception.code, 2)
