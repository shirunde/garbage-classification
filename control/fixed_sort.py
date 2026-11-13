"""One fixed-center pick; model coordinates validate placement, not robot XY."""

from dataclasses import replace
from math import isfinite
from statistics import mean

OBSERVATION_POSE = [90, 130, 0, 0, 90]
FIXED_TARGET_ROI = (160, 280, 460, 479)  # Measured observation: 640x480, one block.
DROP_COLORS = {"recyclable": "blue", "hazardous": "red", "kitchen": "green", "other": "yellow"}


class TargetRejected(ValueError):
    def __init__(self, message, observations=None):
        super().__init__(message)
        self.observations = list(observations or [])


def _check_location(item):
    x0, y0, x1, y1 = FIXED_TARGET_ROI
    if not all(isfinite(float(value)) for value in (item.u, item.v, item.conf)):
        raise TargetRejected("检测坐标或置信度无效，未执行抓取")
    if not (x0 <= item.u <= x1 and y0 <= item.v <= y1):
        raise TargetRejected("检测点偏离固定抓取区；请把单个方块放回已验证的中心位置")
    if item.cls not in DROP_COLORS:
        raise TargetRejected("Unknown model category")


def select_target(detector, samples=5, min_confidence=0.70):
    if samples < 3:
        raise ValueError("At least three observations are required")
    if not 0 <= min_confidence <= 1:
        raise ValueError("Confidence must be between zero and one")
    accepted = []
    observations = []
    for _ in range(samples):
        item = detector.detect()
        observations.append(None if item is None else dict(item.__dict__))
        if item is None or item.conf < min_confidence:
            continue
        try:
            _check_location(item)
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
