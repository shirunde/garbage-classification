"""相机识别一个固定点方块，按模型类别连续完成一次抓取投放。"""

import argparse
import json
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from control.fixed_sort import (
    DROP_COLORS, FIXED_TARGET_ROI, OBSERVATION_POSE,
    TargetRejected, pick_selected, select_target,
)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="执行一次固定点识别、抓取和投放")
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument("--image", help="640x480静态图片诊断，仅识别")
    parser.add_argument("--model", default=None)
    parser.add_argument("--samples", type=int, default=5)
    parser.add_argument("--min-confidence", type=float, default=0.70)
    args = parser.parse_args(argv)
    if args.execute and args.image:
        parser.error("--image 仅用于诊断，不能与 --execute 同用")
    if args.samples < 3 or not 0 <= args.min_confidence <= 1:
        parser.error("samples >= 3，confidence 必须在0到1之间")
    record = {
        "id": uuid.uuid4().hex, "ts": time.time_ns() // 1000000,
        "mode": "model_fixed_center", "execute": args.execute,
        "roi": list(FIXED_TARGET_ROI), "samples": args.samples,
        "min_confidence": args.min_confidence,
        "command_sequence_completed": False, "physical_success_confirmed": None,
    }
    detector = camera = None
    started = time.monotonic()
    try:
        import cv2
        from vision.detector import AscendDetector

        if args.image:
            image = cv2.imread(args.image)
            if image is None or image.shape[:2] != (480, 640):
                raise ValueError("诊断图片必须是观察姿态下的640x480图像")

            def source():
                return image.copy()
        else:
            camera = cv2.VideoCapture(args.camera, cv2.CAP_V4L2)
            camera.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            camera.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            if not camera.isOpened():
                raise RuntimeError("摄像头打开失败")

            def source():
                ok, frame = camera.read()
                if not ok or frame is None or frame.shape[:2] != (480, 640):
                    raise RuntimeError("摄像头未返回640x480画面")
                return frame
            source()

        detector = AscendDetector(model_path=args.model, frame_source=source)
        record["model"] = str(detector.model_path)
        arm = None
        if args.execute:
            from control.arm import BoardArm
            from control import poses
            arm = BoardArm()
            print("移到固定观察姿态", flush=True)
            arm._move(poses.TOP, 1800)
            arm._move(OBSERVATION_POSE, 1800)
        if camera is not None:
            # 丢弃调整姿态前积存的画面。
            for _ in range(5):
                source()
        target, observations = select_target(detector, args.samples, args.min_confidence)
        record.update(detection=dict(target.__dict__), observations=observations,
                      drop_color=DROP_COLORS[target.cls])
        print(json.dumps({"recognition": target.__dict__,
                          "drop_color": DROP_COLORS[target.cls]}, ensure_ascii=False),
              flush=True)
        if args.execute:
            action_start = time.monotonic()
            record["command_sequence_completed"] = pick_selected(arm, target)
            record["action_cost_ms"] = round((time.monotonic() - action_start) * 1000)
            print("一次连续动作已完成；实际夹取和落点以现场观察为准。", flush=True)
        else:
            print("识别预检完成，未启动机械臂。加 --execute 可执行一次固定点分拣。", flush=True)
        record["status"] = "completed" if args.execute else "dry_run"
        return 0
    except KeyboardInterrupt:
        record.update(status="interrupted", error="用户中止")
        print("已中止，不再下发后续运动。", file=sys.stderr, flush=True)
        return 130
    except Exception as exc:
        record.update(status="stopped", error=str(exc))
        if isinstance(exc, TargetRejected):
            record["observations"] = exc.observations
        print("已停止: " + str(exc), file=sys.stderr, flush=True)
        return 2
    finally:
        for resource, method in ((detector, "close"), (camera, "release")):
            if resource is not None:
                try:
                    getattr(resource, method)()
                except Exception as exc:
                    record.setdefault("cleanup_errors", []).append(str(exc))
        record["total_cost_ms"] = round((time.monotonic() - started) * 1000)
        folder = ROOT / "records"
        folder.mkdir(exist_ok=True)
        path = folder / ("fixed_sort_" + record["id"] + ".json")
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
        print("运行记录: " + str(path), flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
