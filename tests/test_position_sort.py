import json
import unittest
from unittest.mock import Mock, patch

from control import poses
from control.arm import CommError
from control.calibration import CalibrationError, CalibrationRecord
from control.position_sort import execute_position, plan_position
from scripts import run_position_sort


class PositionSortTests(unittest.TestCase):
    def setUp(self):
        self.calibration = CalibrationRecord(
            [(100, 100), (500, 100), (500, 400), (100, 400)],
            [(-.1, .2), (.1, .2), (.1, .35), (-.1, .35)], .22,
        )
        self.solver = Mock()
        self.solver.solve.return_value = [90, 70, 40, 35, 250]

    def test_converts_off_center_pixel_and_checks_both_heights(self):
        plan = plan_position(self.calibration, self.solver, 400, 250, .04, "other")
        for actual, expected in zip(plan.pickup_m, (.05, .275, .22)):
            self.assertAlmostEqual(actual, expected)
        self.assertAlmostEqual(plan.approach_m[2], .26)
        self.assertEqual(self.solver.solve.call_count, 2)

    def test_outside_workspace_never_calls_ik(self):
        with self.assertRaises(CalibrationError):
            plan_position(self.calibration, self.solver, 600, 250, .04)
        self.solver.solve.assert_not_called()

    def test_bad_approach_solution_rejects_whole_plan(self):
        self.solver.solve.side_effect = [[90, 70, 40, 35, 250], [90, 70, 40, 35, 280]]
        with self.assertRaisesRegex(ValueError, "无效关节角"):
            plan_position(self.calibration, self.solver, 400, 250, .04)

    def test_approach_check_never_descends_or_closes_claw(self):
        self.solver.solve.side_effect = [[90, 70, 40, 35, 250], [90, 80, 40, 35, 250]]
        plan = plan_position(self.calibration, self.solver, 400, 250, .04, "other")
        arm = Mock()
        inspect = Mock()
        execute_position(arm, plan, inspect_approach=inspect)
        inspect.assert_called_once()
        arm._clamp.assert_not_called()
        moved = [call.args[0] for call in arm._move.call_args_list]
        self.assertIn(plan.approach_joints_deg, moved)
        self.assertNotIn(plan.pickup_joints_deg, moved)

    def test_pixel_preview_never_opens_camera_or_arm(self):
        with patch.object(run_position_sort.CalibrationRecord, "load", return_value=self.calibration), \
             patch.object(run_position_sort, "RosKinematicsClient", return_value=self.solver), \
             patch.object(run_position_sort, "read_target") as camera, \
             patch("control.arm.BoardArm") as arm, patch("builtins.print"):
            self.assertEqual(run_position_sort.main([
                "--calibration", "measured.json", "--clearance-m", ".04", "--pixel", "400", "250",
            ]), 0)
            camera.assert_not_called()
            arm.assert_not_called()

    def test_map_only_never_initializes_ik_camera_or_arm(self):
        with patch.object(run_position_sort.CalibrationRecord, "load", return_value=self.calibration), \
             patch.object(run_position_sort, "RosKinematicsClient") as solver, \
             patch.object(run_position_sort, "read_target") as camera, \
             patch("control.arm.BoardArm") as arm, patch("builtins.print") as output:
            self.assertEqual(run_position_sort.main([
                "--calibration", "measured.json", "--map-only", "--pixel", "400", "250",
            ]), 0)
            result = json.loads(output.call_args.args[0])
            self.assertAlmostEqual(result["x_m"], .05)
            self.assertAlmostEqual(result["y_m"], .275)
            self.assertEqual(result["z_m"], .22)
            solver.assert_not_called()
            camera.assert_not_called()
            arm.assert_not_called()

    def test_full_cycle_lifts_from_pickup_before_using_class_bin(self):
        self.solver.solve.side_effect = [[90, 70, 40, 35, 250], [90, 80, 40, 35, 250]]
        plan = plan_position(self.calibration, self.solver, 400, 250, .04, "other")
        arm = Mock()
        execute_position(arm, plan)
        moved = [call.args[0] for call in arm._move.call_args_list]
        self.assertEqual(moved, [
            poses.TOP, plan.approach_joints_deg, plan.pickup_joints_deg,
            plan.approach_joints_deg, poses.TOP, poses.BIN_POSES["other"],
            poses.TOP, poses.MOULD,
        ])

    def test_communication_error_aborts_remaining_motion(self):
        plan = plan_position(self.calibration, self.solver, 400, 250, .04, "other")
        arm = Mock()
        arm._move.side_effect = [None, CommError("I2C failed")]
        with self.assertRaises(CommError):
            execute_position(arm, plan)
        self.assertEqual(arm._move.call_count, 2)
        arm._clamp.assert_not_called()
