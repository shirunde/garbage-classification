"""分拣状态机。检测、机械臂、表情都从外面注入，方便本机用假对象测试。"""

from shared.schemas import BIN_BY_CLASS, Reason, SortEvent
from control.arm import CommError

LOW_CONF = 0.5
HIGH_CONF = 0.7


class NullSink:
    def show_pending(self, cls):
        return None


class SmileScript:
    """按预定结果模拟表情确认和成功反馈。真机换成摄像头表情。"""

    def __init__(self, answers):
        self.answers = list(answers)

    def wait(self, timeout_ms):
        if not self.answers:
            return False
        return self.answers.pop(0)


class Sorter:
    def __init__(self, detector, arm, color_tracker, face, clock, sink=None, confirm_timeout_ms=3000):
        self.detector = detector
        self.arm = arm
        self.color_tracker = color_tracker
        self.face = face
        self.clock = clock
        self.sink = sink or NullSink()
        self.confirm_timeout_ms = confirm_timeout_ms
        self.halted = False
        self._seq = 0

    def run_once(self):
        if self.halted:
            raise CommError("通信异常后已停止下发新运动")
        started = self.clock()
        detect = self.detector.detect()
        if detect is None:
            return self._event("", 0, False, started, Reason.TIMEOUT_NO_TARGET)

        detect, confirmed, rejected = self._recover_low_conf(detect)
        if rejected:
            return self._event(detect.cls, 0, False, started, Reason.LOW_CONF_COLOR_TRACK)
        if not confirmed and LOW_CONF <= detect.conf <= HIGH_CONF:
            if not self._confirm(detect.cls):
                return self._event(detect.cls, 0, False, started, Reason.NEED_CONFIRM_TIMEOUT)

        try:
            grasped = self.arm.grasp(detect)
            if not grasped:
                grasped = self.arm.grasp(detect)
        except CommError:
            self.halted = True
            return self._event(detect.cls, 0, False, started, Reason.COMM_ERROR)

        if not grasped:
            self.arm.go_safe()
            return self._event(detect.cls, 0, False, started, Reason.GRASP_FAIL)

        if self.face.wait(self.confirm_timeout_ms):
            self.arm.wave()
        return self._event(detect.cls, BIN_BY_CLASS[detect.cls], True, started, Reason.OK)

    def _recover_low_conf(self, detect):
        if detect.conf >= LOW_CONF:
            return detect, False, False
        tracked = self.color_tracker.locate(detect)
        if tracked is not None and tracked.conf >= LOW_CONF:
            return tracked, False, False
        if not self._confirm(detect.cls):
            return detect, False, True
        return detect, True, False

    def _confirm(self, cls):
        self.sink.show_pending(cls)
        try:
            return self.face.wait(self.confirm_timeout_ms)
        finally:
            self.sink.show_pending(None)

    def _event(self, cls, bin_id, ok, started, reason):
        self._seq += 1
        now = self.clock()
        return SortEvent(
            event_id=str(self._seq),
            ts=now,
            cls=cls,
            bin_id=bin_id,
            ok=ok,
            cost_ms=max(0, now - started),
            reason=reason,
        )
