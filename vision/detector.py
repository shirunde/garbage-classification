"""检测器接口。本机开发使用脚本化假数据，板端再换成昇腾推理。"""

from shared.schemas import DetectResult


class MockDetector:
    def __init__(self, script):
        self.script = list(script)

    def detect(self):
        if not self.script:
            return None
        item = self.script.pop(0)
        if item is None:
            return None
        return item if isinstance(item, DetectResult) else DetectResult(**item)


class ScriptedColorTracker:
    """置信度低于 0.5 时的颜色追踪兜底。返回 None 表示仍然失败。"""

    def __init__(self, result=None):
        self.result = result

    def locate(self, detect):
        return self.result


class AscendDetector:
    """板端适配占位。课上联调时在这里接入 ais_bench / .om 模型。"""

    def __init__(self, model_path):
        self.model_path = model_path

    def detect(self):
        raise NotImplementedError(
            f"昇腾推理尚未接入，模型路径预留为 {self.model_path}。平时请使用 MockDetector。"
        )
