"""语音和按钮共用的分拣会话。一次失败不挡住后续目标，无目标或通信异常则回到待机。"""

from shared.schemas import Reason
from control.arm import CommError
from control.voice import parse_command


class SortingSession:
    def __init__(self, sorter, sink):
        self.sorter = sorter
        self.sink = sink
        self.mode = "idle"

    def handle_text(self, text):
        command = parse_command(text)
        if command is None:
            return False
        self.handle(command)
        return True

    def handle(self, command):
        if command == "start":
            if not self.sorter.halted:
                self.mode = "running"
        elif command == "pause":
            if self.mode == "running":
                self.mode = "paused"
        elif command == "stop":
            self.mode = "idle"

    def tick(self):
        if self.mode != "running":
            return None
        try:
            event = self.sorter.run_once()
        except CommError:
            self.mode = "idle"
            return None
        self.sink.publish(event)
        if event.reason in (Reason.TIMEOUT_NO_TARGET, Reason.COMM_ERROR):
            self.mode = "idle"
        return event
