import contextlib
import io
import json
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from control import poses
from control.fixed_sort import OBSERVATION_POSE
from shared.schemas import DetectResult
from scripts import run_fixed_sort as cli


class FixedSortCliTests(unittest.TestCase):
    def run_entry(self, args, classes=None, camera_open=True, fail_grasp=False, lift_detections=(),
                  placement_detections=None, qwen_status=None):
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
            imwrite=lambda path, frame: Path(path).write_bytes(b"test JPEG") > 0,
        )

        class Detector:
            def __init__(self, model_path, frame_source):
                self.source = frame_source
                self.model_path = Path("model.om")
                self.items = iter(classes)
                self.lift_detections = iter(lift_detections)
                self.placement_detections = iter(placement_detections or ())
            def detect(self):
                self.source()
                cls = next(self.items)
                return None if cls is None else DetectResult(cls, 300, 400, .9, 1)
            def close(self):
                calls.append("detector_closed")
            def detect_frame(self, frame):
                return next(self.lift_detections, None)
            def detect_all(self, frame):
                return next(self.placement_detections)

        class Arm:
            def __init__(self, after_lift=None):
                self.after_lift = after_lift
                calls.append("arm_loaded")
            def _move(self, pose, duration):
                calls.append(("move", list(pose)))
            def grasp(self, target):
                calls.append(("grasp", target.cls, target.u, target.v))
                if fail_grasp:
                    raise RuntimeError("I2C failed")
                if self.after_lift is not None:
                    self.after_lift(target)
                return True
            def move_bin_camera(self, view):
                calls.append(("pan", view))
            def at_camera_observation(self):
                return True

        detector_module = types.ModuleType("vision.detector")
        detector_module.AscendDetector = Detector
        delivery = MagicMock()
        delivery.__enter__.return_value.status = 201
        with tempfile.TemporaryDirectory() as folder:
            if placement_detections is not None:
                rois = Path(folder) / 'rois.json'
                rois.write_text('{"other": [500, 250, 620, 350]}', encoding='utf-8')
                args = args + ['--bin-rois', str(rois)]
            with patch.object(cli, "ROOT", Path(folder)), \
                 patch.dict("sys.modules", {"cv2": cv2, "vision.detector": detector_module}), \
                 patch("vision.live_camera.camera_source_if_running", return_value=None), \
                 patch("vision.placement_client.verify_placement", return_value=qwen_status), \
                 patch("shared.event_sink.urlopen", return_value=delivery), \
                 patch("control.arm.BoardArm", Arm), \
                 patch("builtins.input", side_effect=AssertionError("Unexpected operator prompt")), \
                 contextlib.redirect_stdout(io.StringIO()), \
                 contextlib.redirect_stderr(io.StringIO()):
                code = cli.main(args + ['--dashboard-url', 'http://127.0.0.1:18765' if qwen_status else ''])
            record = json.loads(next((Path(folder)/"records").glob("*.json")).read_text(encoding="utf-8"))
            if record.get("grasp_verification", {}).get("photo"):
                self.assertTrue(Path(record["grasp_verification"]["photo"]).is_file())
        return code, calls, record

    def test_read_only_default_never_loads_arm(self):
        code, calls, record = self.run_entry([])
        self.assertEqual(code, 0)
        self.assertNotIn("arm_loaded", calls)
        self.assertEqual(record["drop_color"], "yellow")
        self.assertEqual(record["status"], "dry_run")
        self.assertFalse(record["command_sequence_completed"])
        self.assertNotIn('event', record)
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
        self.assertEqual(record['event']['reason'], 'command_complete')
        self.assertFalse(record['event']['ok'])

    def test_conflicting_recognition_never_grasps(self):
        code, calls, record = self.run_entry(["--execute"], ["other"]*4+["recyclable"])
        self.assertEqual(code, 2)
        self.assertFalse(any(isinstance(x, tuple) and x[0]=="grasp" for x in calls))
        self.assertEqual(len(record["observations"]), 5)
        self.assertEqual(record["status"], "skipped")

    def test_verified_photo_records_grasp_but_does_not_confirm_placement(self):
        held = DetectResult("other", 300, 400, .9, 2)
        code, _, record = self.run_entry(
            ["--execute", "--verify-grasp", "--grasp-roi", "250", "350", "350", "450"],
            lift_detections=(held, None, held),
        )
        self.assertEqual(code, 0)
        self.assertEqual(record["grasp_verification"]["result"], "grasp_confirmed")
        self.assertEqual(record["event"]["reason"], "command_complete")

    def test_background_and_conflicting_detections_do_not_confirm(self):
        background = DetectResult("other", 540, 140, .98, 2)
        conflicting = DetectResult("recyclable", 300, 400, .95, 3)
        code, _, record = self.run_entry(
            ["--execute", "--verify-grasp", "--grasp-roi", "250", "350", "350", "450"],
            lift_detections=(background, conflicting, None),
        )
        self.assertEqual(code, 0)
        self.assertEqual(record["attempts"], 1)
        self.assertEqual(record["grasp_verification"]["result"], "unverified")
        self.assertEqual(record["event"]["reason"], "command_complete")

    def test_capture_without_calibrated_roi_keeps_grasp_unverified(self):
        held = DetectResult("other", 300, 400, .98, 2)
        code, _, record = self.run_entry(
            ["--execute", "--verify-grasp"], lift_detections=(held, held, held),
        )
        self.assertEqual(code, 0)
        self.assertEqual(record["grasp_verification"]["result"], "unverified")

    def test_new_block_in_target_bin_reports_verified_success(self):
        source = DetectResult("other", 300, 400, .98, 2)
        placed = DetectResult("other", 570, 300, .9, 3)
        code, _, record = self.run_entry(
            ["--execute", "--verify-placement"],
            placement_detections=([source], [source], [], [source, placed], [placed], []),
        )
        self.assertEqual(code, 0)
        self.assertTrue(record["physical_success_confirmed"])
        self.assertTrue(record["event"]["ok"])
        self.assertEqual(record["event"]["reason"], "ok")

    def test_target_bin_photos_between_pan_and_return(self):
        code, calls, record = self.run_entry(
            ["--execute", "--verify-placement", "--pan-to-bin"],
        )
        self.assertEqual(code, 0)
        self.assertEqual(calls[:5], [
            "arm_loaded", ("grasp", "other", 320.0, 240.0),
            ("move", OBSERVATION_POSE), ("pan", (75, 130)), ("pan", (90, 130)),
        ])
        evidence = record["placement_verification"]
        self.assertEqual(evidence["camera_base_deg"], 75)
        self.assertNotIn("before", evidence)
        self.assertIn("photo", evidence["after"])

    def test_qwen_placement_result_is_used_by_the_event(self):
        for status, reason, ok in (("in_bin", "ok", True), ("not_in_bin", "placement_failed", False),
                                   ("uncertain", "command_complete", False)):
            with self.subTest(status=status):
                code, _, record = self.run_entry(
                    ["--execute", "--verify-placement", "--pan-to-bin", "--qwen-verify"],
                    qwen_status=status,
                )
                self.assertEqual(code, 0)
                self.assertEqual(record["placement_verification"]["model_status"], status)
                self.assertEqual(record["event"]["reason"], reason)
                self.assertEqual(record["event"]["ok"], ok)

    def test_preexisting_block_or_wrong_bin_keeps_placement_unverified(self):
        in_bin = DetectResult("other", 570, 300, .9, 2)
        outside = DetectResult("other", 300, 400, .98, 2)
        for frames in (([in_bin], [], [], [in_bin], [in_bin], [in_bin]),
                       ([], [], [], [outside], [outside], [outside])):
            with self.subTest(frames=frames):
                code, _, record = self.run_entry(
                    ["--execute", "--verify-placement"], placement_detections=frames,
                )
                self.assertEqual(code, 0)
                self.assertIsNone(record["physical_success_confirmed"])
                self.assertEqual(record["event"]["reason"], "command_complete")

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
        self.assertEqual(record['event']['reason'], 'comm_error')
        self.assertFalse(record["command_sequence_completed"])
        self.assertIn("detector_closed", calls)
        self.assertIn("camera_released", calls)

    def test_still_image_cannot_enable_motion(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as caught:
                cli.main(["--execute", "--image", "test.jpg"])
        self.assertEqual(caught.exception.code, 2)
