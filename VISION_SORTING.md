# Board vision and sorting

## 固定点识别并分拣一次

当前固定抓取点已在真机调试，四个投放位对应：可回收/蓝、有害/红、厨余/绿、其他/黄。使用下面的入口可直接读取相机和模型类别，连续完成一次抓取、投放和返回：

    cd /root/garbage-classification
    bash scripts/run_fixed_sort.sh --execute

把一个方块放在此前示教的固定抓取位置。程序先移到观察姿态，读取5帧；至少3帧达到0.70置信度，且有效帧类别一致、目标位于观察画面的固定区域内，才会抓取。该模式使用既有固定关节姿态，不进行视觉坐标到机械臂XY换算，不能任意摆放方块。

只检查识别、不驱动机械臂时省略 --execute（需已处于观察姿态）：

    bash scripts/run_fixed_sort.sh
    bash scripts/run_fixed_sort.sh --image /path/to/observation_640x480.jpg

模型识别出的类别决定投放位，没有指定类别或颜色强制覆盖。多帧一致不能保证类别正确；此前黄色方块曾被高置信度误判，仍需现场核对模型结果。动作异常时不自动重复抓取。每次运行的识别帧摘要、类别、投放颜色和动作状态写入 records/fixed_sort_*.json；命令序列完成与现场抓取成功分别记录。

## What is wired

- `vision.detector.AscendDetector` captures one frame, runs the Atlas OM model at `models/blocks4_v3/blocks4_yolov8n.om`, and returns the top detection as `(class, u, v, confidence)`. The model binary is ignored by Git; download the `assets-v4` release asset linked in `vision/MODEL_SOURCE.md` and place the OM file at that path after cloning.
- `control.calibration.CalibrationRecord` maps image pixels to arm-base XY using four measured correspondences, and rejects detections outside the calibrated polygon.
- `control.kinematics.RosKinematicsClient` calls the board's `/trial_service` IK service. It rejects targets below 0.20 m because the current service treats those as a separate special-height mode.
- `control.arm.BoardArm` uses the returned joint angles for the pickup, then the project's configured class-specific bin poses.
- Camera/inference exceptions now create a `vision_error` event, pause the session, and use wall-clock milliseconds for event timestamps while measuring duration with a monotonic clock.
- `scripts/run_board_sorting.py --recognize-only` exercises camera and model inference without loading the arm driver. `--enable-arm` enables one sort per Enter key press and writes JSONL events.
- `scripts/run_board_sorting.sh` loads the installed Ascend, ROS 2, workspace, and Arm_Lib environments before launching the Python entry point.

## Calibration required before arm mode

Do not use the example coordinates below as a real calibration. Replace them with four measured points around the reachable flat work area. `image_points_px` must be corners in the detector's original camera frame, ordered around the perimeter. For each corner, `base_xy_points_m` must contain the corresponding XY in the robot-base frame, in meters and in the same order. `fixed_height_m` is the end-effector target height and must be at least 0.20 m for the current IK server.

The fixed pickup and bin poses in `control/poses.py` were adjusted during the November 13 board trials. These taught poses support the fixed-point mode above; they do not establish a per-pixel calibration. Per-pixel calibration has not been physically validated on this setup.

## Run

After pulling the branch, run the read-only preflight first. It does not open Arm_Lib or send servo/I2C commands:

```bash
cd /root/garbage-classification
bash scripts/diagnose_board.sh
```

After downloading the OM model into the path above, test recognition only. This does not load the arm driver. A still image isolates model inference from camera setup:

```bash
bash scripts/run_board_sorting.sh --recognize-only --image /path/to/sample.jpg
```

Use `--camera 0` instead of `--image` to exercise a live camera once the board exposes it as a V4L2 device.

To send hardware events to the dashboard, run it in a second terminal and configure the sort runner with its local URL:

```bash
python3 scripts/run_dashboard.py --host 0.0.0.0 --port 8765
bash scripts/run_board_sorting.sh --enable-arm --camera 0 --calibration /path/to/calibration.json --dashboard-url http://127.0.0.1:8765
```

The runner always appends events to local JSONL. Dashboard posting is optional; delivery failures are reported without discarding the local log.

Arm mode requires the `trial_service` IK server to be running in another terminal. Use the dashboard-enabled command above, a measured calibration JSON, and a clear, supervised test area.

The initial model is a public course-project model, not yet evaluated against this team's own collected dataset. Upstream reports mAP@0.5 of 0.952 from 136 real and 800 synthetic images; this is not a measurement on the current camera/board. Record class counts for the team's own labeled data before claiming the course acceptance metric. See `vision/MODEL_SOURCE.md` for source and license notes.

## Acceptance checklist

These are project requirements, not results measured on this board yet:

- Collect and label at least 200 images per category from the actual work area, including normal and dim lighting; keep per-category source/count records.
- Evaluate the four categories on a held-out set and report mAP@0.5; target is at least 0.75. The upstream model's reported 0.952 is not this project's evaluation.
- Measure board inference latency and target at most 150 ms per frame.
- After camera and calibration are ready, run 10 end-to-end sorts. Target at least 8 successes, with each sort completed within 20 seconds.
- Record no-target, low-confidence, failed-grasp, and communication-error cases in the event log and verify the recovery behavior.

Do not mark these items complete from the model's upstream report or from software wiring alone.
