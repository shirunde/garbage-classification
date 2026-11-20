"""Plan one fixed-height pick in the measured camera workspace."""

from dataclasses import dataclass
from math import isfinite

from control import poses


@dataclass(frozen=True)
class PositionPlan:
    category: str | None
    pixel: tuple
    pickup_m: tuple
    approach_m: tuple
    pickup_joints_deg: tuple
    approach_joints_deg: tuple


def check_calibration(calibration, clearance_m=None):
    if not calibration.ready():
        raise ValueError("需要四对有效标定点和受当前 IK 支持的实测抓取高度")
    for points in (calibration.image_points, calibration.base_xy_points):
        turns = []
        for i in range(4):
            a, b, c = (points[(i + offset) % 4] for offset in range(3))
            turns.append((b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0]))
        if not (all(turn > 0 for turn in turns) or all(turn < 0 for turn in turns)):
            raise ValueError("标定点须按凸四边形周边顺序排列")
    if clearance_m is not None and (not isfinite(clearance_m) or clearance_m <= 0):
        raise ValueError("接近位必须高于抓取位，请填写实测的高度差")


def _joint_pose(solver, point):
    joints = tuple(solver.solve(*point))
    limits = (180, 180, 180, 180, 270)
    if len(joints) != len(limits) or not all(
        isfinite(angle) and 0 <= angle <= limit for angle, limit in zip(joints, limits)
    ):
        raise ValueError("逆运动学返回无效关节角")
    return joints


def plan_position(calibration, solver, u, v, clearance_m, category=None):
    check_calibration(calibration, clearance_m)
    if category is not None and category not in poses.BIN_POSES:
        raise ValueError("类别没有对应的投放位")
    pickup = calibration.pixel_to_plane(u, v)
    x, y, z = pickup
    approach = (x, y, z + clearance_m)
    if not isfinite(approach[2]):
        raise ValueError("接近位高度无效")
    return PositionPlan(category, (u, v), pickup, approach,
                        _joint_pose(solver, pickup), _joint_pose(solver, approach))


def execute_position(arm, plan, inspect_approach=None):
    bin_pose = None if inspect_approach else poses.BIN_POSES[plan.category]
    arm._move(poses.TOP, 1800)
    arm._move(plan.approach_joints_deg, 1800)
    if inspect_approach:
        inspect_approach()
    else:
        arm._clamp(False)
        arm._move(plan.pickup_joints_deg, 1800)
        arm._clamp(True)
        arm._move(plan.approach_joints_deg, 1800)
        arm._move(poses.TOP, 1800)
        arm._move(bin_pose, 1800)
        arm._clamp(False)
        arm._move_up()
    arm._move(poses.TOP, 1800)
    arm._move(poses.MOULD, 1800)
