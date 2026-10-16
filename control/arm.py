"""机械臂接口。MockArm 按预定结果模拟抓取，真机适配留到课上。"""


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


class BoardArm:
    """教育舵机臂适配占位。课上再接到现有抓取程序。"""

    def grasp(self, detect):
        raise NotImplementedError("真机抓取尚未接入。平时请使用 MockArm。")

    def go_safe(self):
        raise NotImplementedError("真机安全位尚未接入。平时请使用 MockArm。")

    def wave(self):
        raise NotImplementedError("真机互动动作尚未接入。平时请使用 MockArm。")
