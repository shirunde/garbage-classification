# 智能机械臂垃圾分拣

在标定工作区内完成识别、固定高度抓取、分类投放，并把结果写到局域网看板。

本仓库是小组共用代码。平时在自己电脑上开发；只有上课连上 Atlas 200I DK A2 时，才接摄像头、昇腾推理和舵机。

远程仓库：`git@github.com:shirunde/garbage-classification.git`

## 分工

| 角色 | 同学 | 主要改哪里 | 平时本机做什么 |
|---|---|---|---|
| 视觉 | 张浩、杨翼 | `vision/`、后续数据集与模型目录 | 定 `detect` 输出；用 `MockDetector` / 脚本假数据测状态机对接；准备训练与标注流程 |
| 控制 | 石润德 | `control/` | 分拣状态机、兜底、标定记录；用 `MockArm` 测抓取重试和安全位 |
| 看板 | 王梓铭 | `dashboard/` | 四个页面、事件展示、待确认类别；用 `POST /api/events` 联调 |

共同约定放在 `shared/schemas.py`。字段要改，先和全组说清楚，再改这一处。

## 本机怎么开始

不需要开发板，不需要 ROS，也不需要昇腾环境。

```bash
git clone git@github.com:shirunde/garbage-classification.git
cd garbage-classification
python3 -m unittest discover -s tests
python3 scripts/run_mock.py
python3 -c "from dashboard.server import serve; serve('0.0.0.0', 8765).serve_forever()"
```

看板页面：

- `/` 总览统计
- `/events` 事件流水
- `/categories` 类别分布
- `/status` 系统与兜底状态

事件写入：`POST /api/events`，字段见下方接口。

## 协作方式

1. 从 `main` 拉最新代码：`git pull origin main`
2. 为自己的功能开分支，例如 `vision/detect-mock`、`dashboard/pages`、`control/fallback`
3. 本机改完后跑：`python3 -m unittest discover -s tests`
4. 推自己的分支，开 Pull Request 合回 `main`
5. 上课前在开发板上 `git pull`，只在板端适配层接硬件

不要在本机和开发板之间用 U 盘来回拷。本机改完推 GitHub，开发板再拉。

开发板路径：`/root/garbage-classification`。板子上的 `ros2_robot_arm` 是课程示例，不要直接往里面塞本组业务代码。

## 目录

```
shared/          detect 与 event 字段（全组共用）
vision/          检测接口。本机用 MockDetector，板端再接 AscendDetector
control/         分拣状态机、语音/按钮会话、标定记录、机械臂接口
dashboard/       局域网 Web 看板
scripts/         假数据演示
tests/           不依赖硬件的测试
```

## 接口约定

视觉输出 `detect`：`cls`、`u`、`v`、`conf`、`ts`，可附 `expr`（`smile` 或 `none`）。

| cls | 含义 | bin_id |
|---|---|---|
| recyclable | 可回收物 | 1 |
| hazardous | 有害垃圾 | 2 |
| kitchen | 厨余垃圾 | 3 |
| other | 其他垃圾 | 4 |

控制输出 `event`：`event_id`、`ts`、`cls`、`bin_id`、`ok`、`cost_ms`、`reason`。

`reason`：`ok`、`low_conf_color_track`、`grasp_fail`、`need_confirm_timeout`、`timeout_no_target`、`comm_error`。

### 开发时不要拆掉的规则

- 类别名只写在 `shared/schemas.py`。数据集标签不同，只改这一处。
- 分拣循环用 `SortingSession`。语音词和按钮都调用 `handle` / `handle_text`，不要各自写一套启动逻辑。
- 置信度低于 0.5：先颜色追踪，仍失败再等笑脸确认；0.5 到 0.7：直接等确认。确认期间看板状态页显示待确认类别。
- 一次抓取失败最多重试 1 次，不挡住后续目标；无目标或通信异常后会话回到待机。
- 像素到平面坐标的换算只加在 `control/calibration.py`。
- 大模型文件、数据集、`__pycache__` 不要提交。`.gitignore` 已忽略 `*.om`、`*.pt`、`datasets/`。

## 本机写什么，课上写什么

| 平时本机 | 课上在开发板 |
|---|---|
| 状态机、兜底、原因码 | 摄像头采集 |
| 看板四个页面和事件接口 | `.om` 推理与耗时 |
| 假检测、假机械臂、假表情 | 真机抓取、安全位、投放点 |
| 单元测试 | 标定、语音麦克风、表情摄像头 |

板端空位：

- `vision/detector.py` 里的 `AscendDetector`
- `control/arm.py` 里的 `BoardArm`
- `control/calibration.py` 里的像素到平面换算
