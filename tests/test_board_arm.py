import unittest
from unittest.mock import patch

from control.arm import BoardArm, CommError
from control import poses
from shared.schemas import DetectResult


class FakeDevice:
    def __init__(self):
        self.writes = []

    def Arm_serial_servo_write(self, servo_id, angle, use_time):
        self.writes.append((servo_id, angle, use_time))
        return None


class BoardArmTest(unittest.TestCase):
    def setUp(self):
        self.sleep_patch = patch("control.arm.time.sleep", return_value=None)
        self.sleep_patch.start()

    def tearDown(self):
        self.sleep_patch.stop()

    def test_grasp_writes_servos_for_known_class(self):
        device = FakeDevice()
        arm = BoardArm(device=device)
        ok = arm.grasp(DetectResult("recyclable", 320, 240, 0.9, 1))
        self.assertTrue(ok)
        self.assertGreater(len(device.writes), 10)
        servo_ids = {item[0] for item in device.writes}
        self.assertIn(6, servo_ids)

    def test_uncalibrated_off_center_target_never_writes_servos(self):
        device = FakeDevice()
        arm = BoardArm(device=device)
        with self.assertRaises(CommError):
            arm.grasp(DetectResult("recyclable", 1, 2, 0.9, 1))
        self.assertEqual(device.writes, [])

    def test_lift_check_precedes_bin_motion(self):
        device = FakeDevice()
        writes_at_check = []

        def verify(target):
            writes_at_check.extend(device.writes)

        arm = BoardArm(device=device, after_lift=verify)
        self.assertTrue(arm.grasp(DetectResult("recyclable", 320, 240, 0.9, 1)))
        self.assertGreater(len(device.writes), len(writes_at_check))
        self.assertEqual(writes_at_check[-6][:2], (6, poses.GRIPPER_CLOSE))
        self.assertEqual([angle for _, angle, _ in writes_at_check[-5:]], poses.TOP)

    def test_unknown_class_returns_false(self):
        device = FakeDevice()
        arm = BoardArm(device=device)

        class FakeDetect:
            cls = "not-a-class"

        self.assertFalse(arm.grasp(FakeDetect()))
        self.assertEqual(device.writes, [])

    def test_camera_observation_moves_shoulder_at_center_then_pans(self):
        class ObservedDevice(FakeDevice):
            angles = [90, 130, 1, 1, 270, 59]

            def Arm_serial_servo_read(self, servo_id):
                return self.angles[servo_id - 1]

            def Arm_serial_servo_write(self, servo_id, angle, use_time):
                super().Arm_serial_servo_write(servo_id, angle, use_time)
                self.angles[servo_id - 1] = angle

        device = ObservedDevice()
        arm = BoardArm(device=device)
        with self.assertRaises(CommError):
            arm.move_bin_camera((50, 110))
        self.assertEqual(device.writes, [])
        device.angles[4] = 90
        arm.move_bin_camera((50, 110))
        arm.move_bin_camera((90, 130))
        self.assertEqual([(servo, angle) for servo, angle, _ in device.writes],
                         [(2, 120), (2, 110), (1, 50), (1, 90), (2, 120), (2, 130)])

    def test_servo_write_failure_raises_comm_error(self):
        class DeadDevice:
            def Arm_serial_servo_write(self, servo_id, angle, use_time):
                raise OSError("I2C error")

        arm = BoardArm(device=DeadDevice())
        with self.assertRaises(CommError):
            arm.go_safe()


if __name__ == "__main__":
    unittest.main()
