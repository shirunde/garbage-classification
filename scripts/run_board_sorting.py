"""Interactive board-side one-target recognition and sorting loop."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from control.arm import BoardArm
from control.calibration import CalibrationRecord
from control.kinematics import RosKinematicsClient
from control.session import SortingSession
from control.sorter import Sorter
from shared.schemas import Reason
from vision.detector import AscendDetector


class NoColorTracker:
    def locate(self, detect):
        return None


class NoFaceConfirmation:
    def wait(self, timeout_ms):
        return False


class EventLog:
    def __init__(self, path):
        self.path = Path(path)

    def show_pending(self, cls):
        return None

    def publish(self, event):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as log:
            log.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=None, help="Ascend .om path; defaults to models/blocks4_v3/blocks4_yolov8n.om")
    parser.add_argument("--camera", type=int, default=0, help="OpenCV camera index")
    parser.add_argument("--image", help="Run one still image instead of opening a camera (recognize-only mode)")
    parser.add_argument("--calibration", help="Measured workspace calibration JSON (required for arm mode)")
    parser.add_argument("--event-log", default=str(ROOT / "events.jsonl"))
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--recognize-only", action="store_true", help="Run one camera/model inference per Enter; never open the arm")
    mode.add_argument("--enable-arm", action="store_true", help="Enable one sort per Enter; requires measured calibration")
    args = parser.parse_args()

    if args.enable_arm:
        if not args.calibration:
            parser.error("--enable-arm 需要 --calibration 标定文件")
        calibration = CalibrationRecord.load(args.calibration)
        if not calibration.ready():
            parser.error("标定 JSON 必须包含四组 image/base 点和 fixed_height_m")

    if args.image and not args.recognize_only:
        parser.error("--image 只能与 --recognize-only 一起使用")

    frame_source = None
    if args.image:
        try:
            import cv2
            image = cv2.imread(args.image)
            if image is None:
                raise ValueError(f"无法读取图片: {args.image}")
            frame_source = lambda: image.copy()
        except Exception as exc:
            print(f"图片读取失败: {exc}", file=sys.stderr)
            return 2

    try:
        detector = AscendDetector(
            model_path=args.model,
            camera_index=args.camera,
            frame_source=frame_source,
        )
    except Exception as exc:
        print(f"视觉初始化失败: {exc}", file=sys.stderr)
        return 2

    if args.recognize_only:
        print("识别模式：按 Enter 识别一帧；输入 q 退出。此模式不会加载机械臂驱动。")
        try:
            if args.image:
                try:
                    result = detector.detect()
                except Exception as exc:
                    print(f"图片推理失败: {exc}", file=sys.stderr)
                    return 3
                print(json.dumps(result.__dict__ if result else {"target": None}, ensure_ascii=False))
                return 0
            while input("detect> ").strip().lower() != "q":
                try:
                    result = detector.detect()
                except Exception as exc:
                    print(f"相机采集或模型推理失败: {exc}", file=sys.stderr)
                    return 3
                print(json.dumps(result.__dict__ if result else {"target": None}, ensure_ascii=False))
        finally:
            detector.close()
        return

    ik = RosKinematicsClient()
    try:
        arm = BoardArm(calibration=calibration, ik_solver=ik)
    except Exception:
        ik.close()
        raise
    sink = EventLog(args.event_log)
    sorter = Sorter(
        detector, arm, NoColorTracker(), NoFaceConfirmation(),
        lambda: time.monotonic_ns() // 1_000_000,
        sink=sink,
        timestamp=lambda: time.time_ns() // 1_000_000,
    )
    session = SortingSession(sorter, sink)

    print("分拣模式：按 Enter 识别并尝试分拣一个目标；输入 q 退出。低置信度目标会跳过。")
    try:
        while True:
            command = input("sort> ").strip().lower()
            if command == "q":
                break
            session.handle("start")
            try:
                event = session.tick()
            except Exception as exc:
                print(f"视觉采集或分拣流程异常，已停止: {exc}", file=sys.stderr)
                break
            finally:
                session.handle("stop")
            if event is not None:
                print(json.dumps(event.to_dict(), ensure_ascii=False))
            if sorter.halted:
                if event is not None and event.reason == Reason.VISION_ERROR:
                    print("相机或视觉推理异常；分拣已暂停，请检查视觉设备后重启。")
                else:
                    print("发生机械臂通信错误；停止后续运动，请检查设备并人工恢复。")
                break
    finally:
        detector.close()
        ik.close()


if __name__ == "__main__":
    main()
