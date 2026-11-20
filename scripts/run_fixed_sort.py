"""相机识别一个固定点方块，按模型类别连续完成一次抓取投放。"""

import argparse
import json
import os
import math
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
from control.fixed_runner import FixedRunner
from control.placement_check import PlacementCheck, load_bin_rois
from shared.event_sink import EventSink
from shared.schemas import Reason, SortEvent


def verify_grasp_photo(cv2, source, detector, target, photo_path, record, roi, min_confidence):
    verification = {'result': 'unverified', 'roi': roi, 'observations': []}
    record['grasp_verification'] = verification
    hits = 0
    try:
        photo_path.parent.mkdir(parents=True, exist_ok=True)
        for _ in range(3):
            source()
        frame = source()
        if not cv2.imwrite(str(photo_path), frame):
            raise OSError('无法保存抓取照片')
        verification['photo'] = str(photo_path)
        print(f'抬起后照片：{photo_path}', flush=True)
        for index in range(3):
            found = detector.detect_frame(frame if index == 0 else source())
            verification['observations'].append(dict(found.__dict__) if found else None)
            if roi and found and found.cls == target.cls and found.conf >= min_confidence:
                left, top, right, bottom = roi
                if left <= found.u < right and top <= found.v < bottom:
                    hits += 1
    except Exception as exc:
        verification['error'] = str(exc)
        print(f'抓取视觉核验失败：{exc}', file=sys.stderr, flush=True)
        return
    verification['matching_frames'] = hits
    if hits >= 2:
        verification['result'] = 'grasp_confirmed'
        print('视觉核验：已夹住，落点待核验。', flush=True)
    elif roi:
        print('视觉核验：夹爪区域的识别证据不足，抓取结果待核验。', flush=True)
    else:
        print('视觉核验：已保存识别结果，需设置可见夹爪区域才能确认抓取。', flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="执行一次固定点识别、抓取和投放")
    parser.add_argument("--verify-grasp", action="store_true", help="夹紧抬起后拍照并自动识别")
    parser.add_argument("--grasp-roi", type=int, nargs=4, metavar=("LEFT", "TOP", "RIGHT", "BOTTOM"),
                        help="640×480 抬起画面的夹爪取物区域，需现场标定")
    parser.add_argument("--verify-placement", action="store_true", help="自动对比投放前后的目标格子")
    parser.add_argument("--pan-to-bin", action="store_true", help="用机载相机转向已示教的目标格拍照并回正")
    parser.add_argument("--qwen-verify", action="store_true", help="用本机看板上的千问服务核验目标格照片")
    parser.add_argument("--bin-rois", type=Path, help="投放格子像素矩形 JSON")
    parser.add_argument("--placement-camera", type=int, help="可选的独立投放观察相机编号")
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument("--image", help="640x480静态图片诊断，仅识别")
    parser.add_argument("--model", default=None)
    parser.add_argument("--samples", type=int, default=5)
    parser.add_argument("--min-confidence", type=float, default=0.70)
    parser.add_argument('--target-timeout', type=float, default=2.0, help='识别观察窗口秒数；底层阻塞需由驱动处理')
    parser.add_argument('--dashboard-url', default=os.environ.get('SORTING_DASHBOARD_URL', 'http://127.0.0.1:8765'))
    parser.add_argument('--event-dir', help='事件日志和补发队列目录，默认 records')
    parser.add_argument('--flush-events-only', action='store_true', help='仅补发积存事件，不加载相机或机械臂')
    args = parser.parse_args(argv)
    if args.execute and args.image:
        parser.error("--image 仅用于诊断，不能与 --execute 同用")
    if args.verify_grasp and not args.execute:
        parser.error("--verify-grasp 需要配合 --execute")
    if args.verify_placement and (not args.execute or args.flush_events_only):
        parser.error("--verify-placement 需要配合 --execute")
    if not args.verify_placement and (args.bin_rois or args.placement_camera is not None):
        parser.error("--bin-rois 和 --placement-camera 需要配合 --verify-placement")
    if args.pan_to_bin and (not args.verify_placement or args.camera != 0
                            or args.placement_camera not in (None, 0)):
        parser.error("--pan-to-bin 需要配合 --verify-placement 使用机载相机 0")
    if args.pan_to_bin and args.bin_rois:
        parser.error("--pan-to-bin 保存目标格照片，固定视角的 --bin-rois 请单独使用")
    if args.qwen_verify and (not args.pan_to_bin or not args.dashboard_url):
        parser.error("--qwen-verify 需要 --pan-to-bin 和 --dashboard-url")
    if args.grasp_roi:
        left, top, right, bottom = args.grasp_roi
        if not args.verify_grasp or not (0 <= left < right <= 640 and 0 <= top < bottom <= 480):
            parser.error("--grasp-roi 需要配合 --verify-grasp，坐标须在 640×480 画面内")
    if args.samples < 3 or not 0 <= args.min_confidence <= 1 or not math.isfinite(args.target_timeout) or args.target_timeout <= 0:
        parser.error("samples >= 3，confidence 必须在0到1之间")
    sink = EventSink(args.event_dir or ROOT / 'records', args.dashboard_url)
    if args.flush_events_only:
        sink.flush()
        remaining = sink.queue.exists() and bool(sink.queue.read_text(encoding='utf-8').strip())
        print('仍有待补发事件' if remaining else '积存事件已补发')
        return 1 if remaining else 0
    if args.execute:
        sink.flush()
    record = {
        "id": uuid.uuid4().hex, "ts": time.time_ns() // 1000000,
        "mode": "model_fixed_center", "execute": args.execute,
        "roi": list(FIXED_TARGET_ROI), "samples": args.samples,
        "min_confidence": args.min_confidence,
        "command_sequence_completed": False, "physical_success_confirmed": None,
    }
    detector = camera = placement_camera = None
    observation_motion = False
    started = time.monotonic()
    try:
        import cv2
        from vision.detector import AscendDetector
        from vision.live_camera import camera_source_if_running

        def open_camera(index):
            cap = cv2.VideoCapture(index, cv2.CAP_V4L2)
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            if not cap.isOpened():
                cap.release()
                raise RuntimeError(f'摄像头 {index} 打开失败')
            return cap

        def read_camera(cap):
            ok, frame = cap.read()
            if not ok or frame is None or frame.shape[:2] != (480, 640):
                raise RuntimeError("摄像头未返回640x480画面")
            return frame

        if args.image:
            image = cv2.imread(args.image)
            if image is None or image.shape[:2] != (480, 640):
                raise ValueError("诊断图片必须是观察姿态下的640x480图像")

            def source():
                return image.copy()
        else:
            source = camera_source_if_running(cv2, args.camera)
            if source is None:
                camera = open_camera(args.camera)

                def source():
                    return read_camera(camera)
            source()

        detector = AscendDetector(model_path=args.model, frame_source=source)
        record["model"] = str(detector.model_path)
        placement_check = None
        if args.verify_placement:
            rois = load_bin_rois(args.bin_rois) if args.bin_rois else {}
            placement_source = source
            if args.placement_camera is not None and args.placement_camera != args.camera:
                placement_camera = open_camera(args.placement_camera)

                def placement_source():
                    return read_camera(placement_camera)

                placement_source()
            verification = {}
            record['placement_verification'] = verification
            placement_check = PlacementCheck(cv2, placement_source, detector, rois,
                                             ROOT / 'records' / f"placement_{record['id']}",
                                             verification, args.min_confidence)
            if args.qwen_verify:
                from vision.placement_client import verify_placement

                def verify_photo(category, photo):
                    return verify_placement(cv2, args.dashboard_url, category, photo)

                placement_check.verify_photo = verify_photo
        arm = None
        if args.execute:
            from control.arm import BoardArm
            from control import poses
            if args.verify_grasp:
                photo_path = ROOT / 'records' / f"grasp_{record['id']}.jpg"

                def after_lift(target):
                    verify_grasp_photo(cv2, source, detector, target, photo_path, record,
                                       args.grasp_roi, args.min_confidence)

                arm = BoardArm(after_lift=after_lift)
            else:
                arm = BoardArm()
            if args.pan_to_bin:
                placement_check.camera_views = poses.BIN_CAMERA_VIEWS
                placement_check.move_camera = arm.move_bin_camera
                placement_check.center_view = tuple(OBSERVATION_POSE[:2])
            if args.pan_to_bin and arm.at_camera_observation():
                print("已在固定观察姿态，直接识别", flush=True)
            else:
                print("移到固定观察姿态", flush=True)
                observation_motion = True
                arm._move(poses.TOP, 1800)
                arm._move(OBSERVATION_POSE, 1800)
                observation_motion = False
        if not args.image:
            # 丢弃调整姿态前积存的画面。
            for _ in range(5):
                source()
        outcome = FixedRunner(detector, arm, sink, placement_check=placement_check).run_once(
            args.samples, args.min_confidence, args.target_timeout,
        )
        record.update(outcome)
        if 'detection' in record:
            record['drop_color'] = DROP_COLORS[record['detection']['cls']]
            print(json.dumps({'recognition': record['detection'], 'drop_color': record['drop_color']}, ensure_ascii=False), flush=True)
        if record['status'] not in ('completed', 'dry_run'):
            print('本次未完成分拣: ' + record.get('error', record['status']), file=sys.stderr)
            return 130 if record['status'] == 'interrupted' else 2
        if record['physical_success_confirmed']:
            print('落点核验通过，已提交分拣成功事件。', flush=True)
        elif record.get('event', {}).get('reason') == Reason.PLACEMENT_FAILED:
            print('千问未在目标格内发现实物，已提交落点失败事件。', flush=True)
        elif args.execute:
            print('动作完成，已提交待核验事件。', flush=True)
        else:
            print('识别预检完成，未启动机械臂。', flush=True)
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
        if args.execute and 'event' not in record:
            reason = Reason.INTERRUPTED if record.get('status') == 'interrupted' else (
                Reason.COMM_ERROR if observation_motion else Reason.VISION_ERROR)
            event = SortEvent(uuid.uuid4().hex, time.time_ns()//1000000, '', 0, False,
                              round((time.monotonic()-started)*1000), reason)
            record['event'] = event.to_dict()
            sink.publish(event)
        for resource, method in ((detector, "close"), (camera, "release"), (placement_camera, "release")):
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
