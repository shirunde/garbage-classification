"""本机识别→抓取样板。用假 detect 覆盖主路径和兜底，不需要摄像头。"""

from control.arm import MockArm
from control.session import SortingSession
from control.sorter import SmileScript, Sorter
from shared.schemas import DetectResult, Reason
from vision.detector import MockDetector, ScriptedColorTracker

STEPS = (
    "高置信度直接抓取",
    "灰区笑脸确认后抓取",
    "灰区超时跳过",
    "低置信度经颜色追踪后抓取",
    "低置信度追踪失败且未确认",
    "抓取失败重试后仍失败",
    "超时无目标，回到待机",
)


def detect(cls, conf, u=320, v=240, ts=1):
    return DetectResult(cls, u, v, conf, ts)


def build_demo(clock, store):
    """构造一条能跑出全部常见 reason 的假数据会话。"""
    detector = MockDetector(
        [
            detect("recyclable", 0.91),
            detect("hazardous", 0.62),
            detect("kitchen", 0.65),
            detect("other", 0.18),
            detect("kitchen", 0.12),
            detect("recyclable", 0.88),
            None,
        ]
    )
    sorter = Sorter(
        detector=detector,
        arm=MockArm([True, True, True, False, False]),
        color_tracker=ScriptedColorTracker([detect("other", 0.82, u=280, v=200), None]),
        face=SmileScript(
            [
                False,
                True,
                False,
                False,
                False,
                False,
                False,
            ]
        ),
        clock=clock,
        sink=store,
    )
    return SortingSession(sorter, store)


EXPECTED_REASONS = (
    Reason.OK,
    Reason.OK,
    Reason.NEED_CONFIRM_TIMEOUT,
    Reason.OK,
    Reason.LOW_CONF_COLOR_TRACK,
    Reason.GRASP_FAIL,
    Reason.TIMEOUT_NO_TARGET,
)
