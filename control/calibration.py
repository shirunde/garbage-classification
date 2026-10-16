"""标定记录。像素到机械臂坐标的换算只放在这里，状态机继续使用像素坐标。"""


class CalibrationRecord:
    def __init__(self):
        self.fixed_height = None
        self.safe_pose = None
        self.bin_pose = {}

    def ready(self):
        return self.fixed_height is not None and len(self.bin_pose) == 4 and self.safe_pose is not None

    def pixel_to_plane(self, u, v):
        raise NotImplementedError("课上完成工作区标定后，在这里把像素换成固定高度下的平面坐标。")
