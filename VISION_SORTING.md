# Board vision and sorting

## 任意平面位置抓取试验入口

现有固定点入口仍使用 `bash scripts/run_fixed_sort.sh --execute`。
任意位置试验使用 `scripts/run_position_sort.sh`，抓取高度固定，投放复用现有四个示教位。

1. 固定好底座和分拣垫，从已示教的观察姿态拍摄 640×480 原图。双击 `scripts/calibrate_workspace.html`，在浏览器中上传照片，沿工作区周边依次点选四角。填入各点在 IK 基座坐标系下的实测 X、Y 和统一的实测抓取高度 Z，单位为米。下载 `calibration.measured.json` 到项目根目录。也可手工填写 `calibration.template.json` 的副本。像素标记应与检测框中心对应的观测平面一致。
2. 启动课程 ROS 2 逆解服务 `/trial_service`。确认服务的坐标轴、末端参考点及高度约定。当前接口拒绝低于 0.20 m 的 Z，实际高度不兼容时先核对服务协议，不能随意抬高抓取高度。
3. 保持机械臂在观察姿态，先用下面的预检命令核对像素坐标、抓取位与接近位的米制坐标和关节角。接近高度差用现场选定的数值。可加 `--pixel U V` 单独检查手工标记，跳过相机识别。
4. 先用 `--approach-only` 空夹爪对点，机械臂停在接近位，按 Enter 返回。由中心向左右、近远逐点核对。之后才用 `--execute` 尝试一次完整抓放。程序不会代替现场确认碰撞间隙、实际夹取和落点。

```bash
bash scripts/run_position_sort.sh --calibration calibration.measured.json --clearance-m <实测高度差>
```

默认仅计算，不初始化舵机。实物验证使用同一相机姿态和分辨率。若观察姿态、相机或底座移动，重新核对标定。逆解和角度范围检查不等于轨迹碰撞检查。

在装有 NumPy 的电脑上，可对未参与标定的像素点运行以下命令，把输出和实测坐标比较。此模式只做坐标换算，无需相机、主板或 ROS。

```bash
python scripts/run_position_sort.py --calibration calibration.measured.json --map-only --pixel 320 240
```

## 固定点识别并分拣一次

当前固定抓取点已在真机调试，四个投放位对应：可回收/蓝、有害/红、厨余/绿、其他/黄。使用下面的入口可直接读取相机和模型类别，连续完成一次抓取、投放和返回：

    cd /root/garbage-classification
    bash scripts/run_fixed_sort.sh --execute

把一个方块放在此前示教的固定抓取位置。程序先移到观察姿态，读取5帧；至少3帧达到0.70置信度，且有效帧类别一致、目标位于观察画面的固定区域内，才会抓取。该模式使用既有固定关节姿态，不进行视觉坐标到机械臂XY换算，不能任意摆放方块。

加上 `--verify-grasp` 可在夹紧并抬到原有过渡高位后自动拍照并推理三帧，照片保存在 `records/grasp_<运行编号>.jpg`，检测结果保存在本轮 JSON 的 `grasp_verification`。用夹空和夹住的实际画面确定可重复的夹爪取物区域后，传入 `--grasp-roi LEFT TOP RIGHT BOTTOM`。三帧中至少两帧检测到中心在该区域内、类别与抓取前一致、置信度达到阈值的方块，终端才会报告已夹住。证据不足时保留待核验并继续原分拣流程。落点仍由现场核对。

使用 `--verify-placement --bin-rois bin_rois.json` 可自动核对投放。相机须从同一视角拍清整块目标格子，可通过 `--placement-camera N` 指定主板上的独立俯拍相机。配置 JSON 的键使用 `recyclable`、`hazardous`、`kitchen` 或 `other`，值为该格子在 640×480 画面中的 `[左, 上, 右, 下]` 像素坐标。矩形须位于目标格内并避开其他格及抓取区。每轮从目标格清空开始。投放前连续三帧未在格内检测到方块，且投放后至少两帧检测到同类方块时，看板计为成功。证据不足时显示待核验。单独传入 `--verify-placement` 可保存两张对照照片，用于定位格子和验证相机视角。

机载相机可用 `--verify-placement --pan-to-bin` 拍目标格的投放后照片。进入程序时若已在中央观察姿态，直接识别。正常抓放后，机械臂抬到张爪观察姿态并将腕部恢复到 90°，再调整肩关节和底座对准目标格。四组实拍角度按底座、肩关节顺序分别为蓝色可回收格 50°、110°，红色有害格 105°、130°，绿色厨余格 128°、110°，黄色其他格 75°、130°。照片保存在板端 `records/placement_*_after.jpg`，拍完回中央。该模式提供给后续视觉核验使用，现有检测模型容易将格子上的印刷色块误认为实物，事件仍记为待核验。

千问接入后，在上述命令追加 `--qwen-verify`，并通过 `--dashboard-url` 指向本机看板的 SSH 转发地址。每轮开始前清空目标格。板端回中央后将目标格裁图发到本机，本机调用千问 `qwen3.8-max`。判为格内有实物时看板记作成功，明确没有实物时记作落点失败，画面看不清或接口不可用时保留待核验。看板使用 `--qwen-base-url` 启用核验，密钥从本机 `QIANWEN_API_KEY` 环境变量读入。

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
