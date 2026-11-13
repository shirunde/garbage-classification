import unittest
from unittest.mock import patch
from control.fixed_sort import TargetRejected, pick_selected, select_target
from control.arm import BoardArm
from control import poses
from shared.schemas import DetectResult


def detection(cls='other', u=300, v=400, conf=.9):
    return DetectResult(cls, u, v, conf, 1)


class Detector:
    def __init__(self, items):
        self.items = iter(items)
    def detect(self):
        return next(self.items)


class FixedSortTests(unittest.TestCase):
    def test_stable_category_preserves_observed_coordinates(self):
        result, observations = select_target(Detector([detection()] * 5))
        self.assertEqual((result.cls, result.u, result.v), ('other', 300, 400))
        self.assertEqual(len(observations), 5)

    def test_conflicting_categories_rejected(self):
        with self.assertRaises(TargetRejected):
            select_target(Detector([detection()] * 4 + [detection('recyclable')]))

    def test_missing_or_weak_majority_rejected(self):
        with self.assertRaises(TargetRejected):
            select_target(Detector([None, detection(conf=.6), None, detection(), detection()]))

    def test_off_center_target_rejected(self):
        with self.assertRaises(TargetRejected):
            select_target(Detector([detection(u=600)] * 5))

    def test_fixed_pick_is_explicit_and_does_not_modify_detection(self):
        class Arm:
            def grasp(self, result):
                self.received = result
                return True
            def _move(self, pose, duration):
                self.return_pose = pose
        arm = Arm()
        target = detection()
        self.assertTrue(pick_selected(arm, target))
        self.assertEqual((arm.received.u, arm.received.v), (320, 240))
        self.assertEqual((target.u, target.v), (300, 400))
        self.assertEqual(arm.return_pose, [90,130,0,0,90])

    def test_failed_action_is_not_retried_or_followed_by_return_motion(self):
        class Arm:
            calls = 0
            def grasp(self, result):
                self.calls += 1
                raise RuntimeError('I2C error')
            def _move(self, *args):
                raise AssertionError('unexpected motion after failure')
        arm = Arm()
        with self.assertRaisesRegex(RuntimeError, 'I2C'):
            pick_selected(arm, detection())
        self.assertEqual(arm.calls, 1)

    def test_false_action_result_stops_before_observation_move(self):
        class Arm:
            def grasp(self, result):
                return False
            def _move(self, *args):
                raise AssertionError("unexpected return motion")
        with self.assertRaises(RuntimeError):
            pick_selected(Arm(), detection())

    def test_rejected_selection_preserves_frame_evidence(self):
        with self.assertRaises(TargetRejected) as caught:
            select_target(Detector([detection()] * 4 + [detection("recyclable")]))
        self.assertEqual(len(caught.exception.observations), 5)

    def test_nonfinite_location_never_reaches_arm(self):
        with self.assertRaises(TargetRejected):
            pick_selected(None, detection(u=float("nan")))

    def test_actual_board_sequence_uses_model_class_drop_pose(self):
        class Device:
            def __init__(self):
                self.writes = []
            def Arm_serial_servo_write(self, servo_id, angle, duration):
                self.writes.append((servo_id, angle, duration))
        with patch("control.arm.time.sleep"):
            for cls, drop_pose in poses.BIN_POSES.items():
                with self.subTest(cls=cls):
                    device = Device()
                    arm = BoardArm(device=device)
                    self.assertTrue(pick_selected(arm, detection(cls=cls)))
                    self.assertIn((1, drop_pose[0], 1000), device.writes)
                    self.assertIn((1, poses.PICK[0], 1000), device.writes)
