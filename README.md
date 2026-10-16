# 智能机械臂垃圾分拣

在标定工作区内完成识别、固定高度抓取、分类投放，并把结果写到局域网看板。本仓库先把接口和状态机定下来，本机用假数据开发；摄像头、昇腾推理和舵机留在开发板课上接入。

## 目录

- `shared`：`detect` 与 `event` 字段
- `vision`：检测接口。`MockDetector` 用于本机，`AscendDetector` 预留板端模型
- `control`：分拣状态机、语音命令、机械臂接口
- `dashboard`：四个页面的 Web 看板
- `scripts/run_mock.py`：跑一条假数据主路径
- `tests`：不依赖板子的状态机和看板测试

## 接口

视觉输出 `detect`：`cls`、`u`、`v`、`conf`、`ts`，可附 `expr`（`smile` 或 `none`）。

类别与投放箱：

| cls | 含义 | bin_id |
|---|---|---|
| recyclable | 可回收物 | 1 |
| hazardous | 有害垃圾 | 2 |
| kitchen | 厨余垃圾 | 3 |
| other | 其他垃圾 | 4 |

控制输出 `event`：`event_id`、`ts`、`cls`、`bin_id`、`ok`、`cost_ms`、`reason`。

`reason` 取 `ok`、`low_conf_color_track`、`grasp_fail`、`need_confirm_timeout`、`timeout_no_target`、`comm_error`。

## 本机运行

```bash
python3 -m unittest discover -s tests
python3 scripts/run_mock.py
python3 -c "from dashboard.server import serve; serve('0.0.0.0', 8765).serve_forever()"
```

看板页面：`/` 总览，`/events` 流水，`/categories` 类别，`/status` 兜底。事件提交到 `POST /api/events`。
