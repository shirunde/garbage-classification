"""机械臂接口。

本机用 MockArm；开发板用 BoardArm（依赖板上的 Arm_Lib，封装课例 test8 的写法）。
"""

from __future__ import annotations

import time

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

    注意：当前 grasp 仍使用固定抓取点 PICK，尚未根据 detect.u/v 换算平面坐标。
    标定完成后，只需替换 pick 位姿或接入 calibration.pixel_to_plane。
    """

    def __init__(self, device=None, pose_set=None):
        self.arm = device if device is not None else _load_arm_device()
        self.poses = pose_set or default_poses
        self.attempts = 0

    def grasp(self, detect):
        self.attempts += 1
        cls = getattr(detect, "cls", None)
        bin_pose = self.poses.BIN_POSES.get(cls)
        if bin_pose is None:
            return False
        try:
            self._clamp(False)
            self._move(self.poses.MOULD, 1000)
            self._move(self.poses.TOP, 1000)
            self._move(self.poses.PICK, 1000)
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
            try:
                result = self.arm.Arm_serial_servo_write(servo_id, angle, use_time)
            except Exception as exc:
                last = exc
                time.sleep(0.05)
                continue
            if result not in (0, None):
                return result
            time.sleep(0.05)
        raise CommError(f"舵机写入失败 id={servo_id} angle={angle} last={last}")
