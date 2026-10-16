"""视觉 detect 与看板 event 的字段约定。"""

from dataclasses import asdict, dataclass


CLASSES = ("recyclable", "hazardous", "kitchen", "other")
BIN_BY_CLASS = {name: index for index, name in enumerate(CLASSES, start=1)}

CLASS_LABELS = {
    "recyclable": "可回收物",
    "hazardous": "有害垃圾",
    "kitchen": "厨余垃圾",
    "other": "其他垃圾",
}


class Reason:
    OK = "ok"
    LOW_CONF_COLOR_TRACK = "low_conf_color_track"
    GRASP_FAIL = "grasp_fail"
    NEED_CONFIRM_TIMEOUT = "need_confirm_timeout"
    TIMEOUT_NO_TARGET = "timeout_no_target"
    COMM_ERROR = "comm_error"

    ALL = (
        OK,
        LOW_CONF_COLOR_TRACK,
        GRASP_FAIL,
        NEED_CONFIRM_TIMEOUT,
        TIMEOUT_NO_TARGET,
        COMM_ERROR,
    )


@dataclass
class DetectResult:
    cls: str
    u: float
    v: float
    conf: float
    ts: int
    expr: str = "none"

    def __post_init__(self):
        if self.cls not in CLASSES:
            raise ValueError(f"未知类别: {self.cls}")
        if not 0.0 <= self.conf <= 1.0:
            raise ValueError("conf 必须在 0 到 1 之间")
        if self.expr not in ("smile", "none"):
            raise ValueError("expr 只能是 smile 或 none")


@dataclass
class SortEvent:
    event_id: str
    ts: int
    cls: str
    bin_id: int
    ok: bool
    cost_ms: int
    reason: str

    def __post_init__(self):
        if self.reason not in Reason.ALL:
            raise ValueError(f"未知原因码: {self.reason}")
        if self.bin_id not in (0, 1, 2, 3, 4):
            raise ValueError("bin_id 必须是 0 到 4")

    def to_dict(self):
        return asdict(self)
