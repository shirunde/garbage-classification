"""机械臂接口。

本机用 MockArm；开发板用 BoardArm（依赖板上的 Arm_Lib，封装课例 test8 的写法）。
"""

from __future__ import annotations

import math
import time
from contextlib import redirect_stdout
from io import StringIO

from control import poses as default_poses


class CommError(Exception):
    """臂侧通信异常。出现后停止下发新的运动。"""


class MockArm:
    def __init__(self, grasp_results=None, link_down_after=None):
        self.grasp_results = list(grasp_results or [])
        self.link_down_after = link_down_after
        self.attempts = 0
        self.safe_moves = 0
        self.waves = 0

    def grasp(self, detect):
        self.attempts += 1
        if self.link_down_after is not None and self.attempts > self.link_down_after:
            raise CommError("臂侧通信异常")
        if not self.grasp_results:
            return True
        return self.grasp_results.pop(0)

    def go_safe(self):
        self.safe_moves += 1

    def wave(self):
        self.waves += 1


def _load_arm_device():
    try:
        from Arm_Lib import Arm_Device
    except ImportError as exc:
        raise ImportError(
            "未找到 Arm_Lib。BoardArm 只能在开发板上使用；本机请用 MockArm。"
        ) from exc
    device = Arm_Device()
    time.sleep(0.1)
    return device


class BoardArm:
    """教育舵机臂。动作序列对齐课例：张开→过渡→抓取点→夹紧→过渡→投放→松开→抬起。

    With a workspace calibration and IK client, the detected pixel is converted
    to a fixed-height base-frame target before any servo command is sent. Without
    calibration, only the taught image-center pickup is permitted.
    """

    def __init__(self, device=None, pose_set=None, calibration=None, ik_solver=None):
        self.arm = device if device is not None else _load_arm_device()
        self.poses = pose_set or default_poses
        self.calibration = calibration
        self.ik_solver = ik_solver
        self.attempts = 0

    def grasp(self, detect):
        self.attempts += 1
        cls = getattr(detect, "cls", None)
        bin_pose = self.poses.BIN_POSES.get(cls)
        if bin_pose is None:
            return False
        try:
            pick_pose = self._resolve_pick_pose(detect)
            self._clamp(False)
            self._move(self.poses.MOULD, 1000)
            self._move(self.poses.TOP, 1000)
            self._move(pick_pose, 1000)
            self._clamp(True)
            self._move(self.poses.TOP, 1000)
            self._move(bin_pose, 1000)
            self._clamp(False)
            self._move_up()
            self._move(self.poses.MOULD, 1100)
            return True
        except CommError:
            raise
        except Exception as exc:
            raise CommError(f"抓取过程异常: {exc}") from exc

    def _resolve_pick_pose(self, detect):
        if self.calibration is None and self.ik_solver is None:
            u = float(getattr(detect, "u", 320.0))
            v = float(getattr(detect, "v", 240.0))
            if abs(u - 320.0) > 1.0 or abs(v - 240.0) > 1.0:
                raise CommError(
                    "检测目标偏离中心，但工作区尚未标定；拒绝使用固定抓取位"
                )
            return self.poses.PICK
        if self.calibration is None or self.ik_solver is None:
            raise CommError("动态抓取必须同时提供工作区标定和 IK 求解器")
        x_m, y_m, z_m = self.calibration.pixel_to_plane(detect.u, detect.v)
        return self.ik_solver.solve(x_m, y_m, z_m)

    def go_safe(self):
        try:
            self._clamp(False)
            self._move_up()
            self._move(self.poses.MOULD, 1100)
        except Exception as exc:
            raise CommError(f"回安全位失败: {exc}") from exc

    def wave(self):
        """分拣成功后的短互动：底座左右摆一下再回中。"""
        try:
            mould = list(self.poses.MOULD)
            left = list(mould)
            right = list(mould)
            left[0] = max(20, mould[0] - 25)
            right[0] = min(160, mould[0] + 25)
            self._move(left, 600)
            self._move(right, 600)
            self._move(mould, 600)
        except Exception as exc:
            raise CommError(f"挥手动作失败: {exc}") from exc

    def _clamp(self, enable):
        angle = self.poses.GRIPPER_CLOSE if enable else self.poses.GRIPPER_OPEN
        self._servo_write(6, angle, 400)
        time.sleep(0.6)

    def _move(self, joints, s_time=500):
        joints = list(joints)
        limits = (180.0, 180.0, 180.0, 180.0, 270.0)
        if len(joints) != len(limits) or not all(
            math.isfinite(float(angle)) and 0.0 <= float(angle) <= limit
            for angle, limit in zip(joints, limits)
        ):
            raise CommError(f"拒绝下发越界关节姿态: {joints}")
        for index, angle in enumerate(joints, start=1):
            use_time = s_time
            if index == 5:
                use_time = int(s_time * 1.2)
                time.sleep(0.01)
            self._servo_write(index, int(angle), use_time)
            time.sleep(0.05)
        time.sleep(s_time / 1000 + 0.15)

    def _move_up(self):
        self._servo_write(2, 90, 1500)
        time.sleep(0.05)
        self._servo_write(3, 90, 1500)
        time.sleep(0.05)
        self._servo_write(4, 90, 1500)
        time.sleep(0.05)

    def _servo_write(self, servo_id, angle, use_time, retries=3):
        last = None
        for _ in range(retries):
            output = StringIO()
            try:
                # The coursework Arm_Lib swallows SMBus exceptions and prints an
                # error while returning None. Capture that message so a failed
                # I2C write is never reported as a successful servo command.
                with redirect_stdout(output):
                    result = self.arm.Arm_serial_servo_write(servo_id, angle, use_time)
                message = output.getvalue().strip()
                if "i2c error" in message.lower():
                    raise CommError(
                        f"机械臂 I2C 写入失败 id={servo_id} angle={angle}: {message}"
                    )
            except CommError:
                raise
            except Exception as exc:
                last = exc
                time.sleep(0.05)
                continue
            if result == 0 or result is None or result:
                return True
            time.sleep(0.05)
        raise CommError(f"舵机写入失败 id={servo_id} angle={angle} last={last}")
