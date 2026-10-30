import unittest
from unittest.mock import patch

from control.arm import BoardArm, CommError
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
        ok = arm.grasp(DetectResult("recyclable", 1, 2, 0.9, 1))
        self.assertTrue(ok)
        self.assertGreater(len(device.writes), 10)
        servo_ids = {item[0] for item in device.writes}
        self.assertIn(6, servo_ids)

    def test_unknown_class_returns_false(self):
        device = FakeDevice()
        arm = BoardArm(device=device)

        class FakeDetect:
            cls = "not-a-class"

        self.assertFalse(arm.grasp(FakeDetect()))
        self.assertEqual(device.writes, [])

    def test_servo_write_failure_raises_comm_error(self):
        class DeadDevice:
            def Arm_serial_servo_write(self, servo_id, angle, use_time):
                raise OSError("I2C error")

        arm = BoardArm(device=DeadDevice())
        with self.assertRaises(CommError):
            arm.go_safe()


if __name__ == "__main__":
    unittest.main()
