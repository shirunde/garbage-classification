"""One fixed-center pick; model coordinates validate placement, not robot XY."""

from dataclasses import replace
from math import isfinite
from statistics import mean
import time
from shared.schemas import Reason

OBSERVATION_POSE = [90, 130, 0, 0, 90]
FIXED_TARGET_ROI = (160, 280, 460, 479)  # Measured observation: 640x480, one block.
DROP_COLORS = {"recyclable": "blue", "hazardous": "red", "kitchen": "green", "other": "yellow"}


class TargetRejected(ValueError):
    def __init__(self, message, observations=None, reason=Reason.TARGET_REJECTED):
        super().__init__(message)
        self.observations = list(observations or [])
        self.reason = reason


def _check_location(item):
    x0, y0, x1, y1 = FIXED_TARGET_ROI
    if not all(isfinite(float(value)) for value in (item.u, item.v, item.conf)):
        raise TargetRejected("检测坐标或置信度无效，未执行抓取")
    if not (x0 <= item.u <= x1 and y0 <= item.v <= y1):
        raise TargetRejected("检测点偏离固定抓取区；请把单个方块放回已验证的中心位置")
    if item.cls not in DROP_COLORS:
        raise TargetRejected("Unknown model category")


def select_target(detector, samples=5, min_confidence=0.70, timeout_sec=2.0,
                  clock=time.monotonic, sleep=time.sleep, location_check=_check_location):
    if samples < 3:
        raise ValueError("At least three observations are required")
    if not 0 <= min_confidence <= 1:
        raise ValueError("Confidence must be between zero and one")
    accepted = []
    observations = []
    if not isfinite(timeout_sec) or timeout_sec <= 0:
        raise ValueError('timeout_sec must be finite and positive')
    deadline = clock() + timeout_sec
    while len(observations) < samples or not any(observations):
        if clock() >= deadline:
            reason = Reason.TIMEOUT_NO_TARGET if not any(observations) else Reason.TARGET_REJECTED
            raise TargetRejected('等待目标超时，回到待机；未执行抓取', observations, reason)
        item = detector.detect()
        observations.append(None if item is None else dict(item.__dict__))
        if clock() >= deadline:
            reason = Reason.TIMEOUT_NO_TARGET if not any(observations) else Reason.TARGET_REJECTED
            raise TargetRejected('识别观察窗口已超时，未执行抓取', observations, reason)
        if item is None or item.conf < min_confidence:
            if len(observations) >= samples and not any(observations):
                sleep(min(.05, max(0, deadline-clock())))
            continue
        try:
            location_check(item)
        except TargetRejected as exc:
            exc.observations = list(observations)
            raise
        accepted.append(item)
    if len(accepted) < samples // 2 + 1:
        raise TargetRejected("有效识别次数不足，未执行抓取", observations)
    if len({item.cls for item in accepted}) != 1:
        raise TargetRejected("多帧识别类别不一致，未执行抓取", observations)
    target = replace(accepted[-1], u=mean(item.u for item in accepted),
                     v=mean(item.v for item in accepted),
                     conf=mean(item.conf for item in accepted))
    return target, observations


def pick_selected(arm, target):
    """Explicit fixed-position mode: use the physically verified PICK pose."""
    _check_location(target)
    completed = arm.grasp(replace(target, u=320.0, v=240.0))
    if not completed:
        raise RuntimeError("固定点动作未完成；不自动重试")
    arm._move(OBSERVATION_POSE, 1800)
    return True
