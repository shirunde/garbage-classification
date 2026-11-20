"""Preview or run one planar pick using a measured workspace calibration."""

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from control.calibration import CalibrationRecord
from control.fixed_sort import select_target
from control.kinematics import RosKinematicsClient
from control.position_sort import check_calibration, execute_position, plan_position


def read_target(camera_index, model, calibration):
    import cv2
    from vision.detector import AscendDetector
    from vision.live_camera import camera_source_if_running

    read_frame = camera_source_if_running(cv2, camera_index)
    camera = None
    detector = None
    try:
        if read_frame is None:
            camera = cv2.VideoCapture(camera_index, cv2.CAP_V4L2)
            if not camera.isOpened():
                raise RuntimeError("无法打开相机")
            camera.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

            def read_frame():
                ok, frame = camera.read()
                if not ok or frame is None or frame.shape[:2] != (480, 640):
                    raise RuntimeError("相机未返回标定使用的 640×480 画面")
                return frame

        for _ in range(5):
            read_frame()
        detector = AscendDetector(model_path=model, frame_source=read_frame)
        # The fixed-point camera ROI is unrelated to the measured planar workspace.
        return select_target(detector, location_check=lambda item: calibration.pixel_to_plane(item.u, item.v))[0]
    finally:
        try:
            if detector is not None:
                detector.close()
        finally:
            if camera is not None:
                camera.release()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--calibration", type=Path, required=True)
    parser.add_argument("--clearance-m", type=float)
    parser.add_argument("--pixel", type=float, nargs=2, metavar=("U", "V"),
                        help="手动输入原图像素，仅计算，不下发动作")
    parser.add_argument("--map-only", action="store_true",
                        help="配合 --pixel 在本机换算基座坐标，无需主板或 ROS")
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument("--model")
    motion = parser.add_mutually_exclusive_group()
    motion.add_argument("--approach-only", action="store_true", help="空夹爪移到目标上方再返回")
    motion.add_argument("--execute", action="store_true", help="执行一次抓取和投放")
    args = parser.parse_args(argv)
    if args.pixel and (args.approach_only or args.execute):
        parser.error("--pixel 仅用于坐标核对")
    if args.map_only and not args.pixel:
        parser.error("--map-only 需要 --pixel U V")
    if not args.map_only and args.clearance_m is None:
        parser.error("计算逆解或执行时需要 --clearance-m")
    try:
        calibration = CalibrationRecord.load(args.calibration)
        if args.map_only:
            check_calibration(calibration)
            x, y, z = calibration.pixel_to_plane(*args.pixel)
            print(json.dumps({"x_m": x, "y_m": y, "z_m": z}))
            return 0
        check_calibration(calibration, args.clearance_m)
        solver = RosKinematicsClient()
        if args.pixel:
            u, v = args.pixel
            category = None
        else:
            print("请从标定时的观察姿态采集画面。", flush=True)
            target = read_target(args.camera, args.model, calibration)
            u, v, category = target.u, target.v, target.cls
        plan = plan_position(calibration, solver, u, v, args.clearance_m, category)
        print(json.dumps(asdict(plan), ensure_ascii=False, indent=2), flush=True)
        if args.execute or args.approach_only:
            from control.arm import BoardArm

            inspect = None
            if args.approach_only:
                inspect = lambda: input("已到目标上方，核对夹爪位置后按 Enter 返回：")
            execute_position(BoardArm(), plan, inspect_approach=inspect)
            print("动作序列完成，请现场核对对点或投放结果。")
    except KeyboardInterrupt:
        print("已中止。", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"本轮已停止：{exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
