"""本机假数据演示。

用法：
  python scripts/run_mock.py              # 终端打印事件
  python scripts/run_mock.py --web        # 同时拉起看板，浏览器看四页
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from control.arm import MockArm
from control.session import SortingSession
from control.sorter import SmileScript, Sorter
from control.voice import START
from dashboard.server import serve
from dashboard.store import EventStore
from shared.schemas import DetectResult
from vision.detector import MockDetector, ScriptedColorTracker


def build_demo(clock, store):
    detector = MockDetector(
        [
            DetectResult("recyclable", 320, 240, 0.91, 1),
            DetectResult("kitchen", 300, 220, 0.62, 2),
            DetectResult("other", 280, 200, 0.18, 3),
            None,
        ]
    )
    arm = MockArm([True, True, True])
    sorter = Sorter(
        detector=detector,
        arm=arm,
        color_tracker=ScriptedColorTracker(DetectResult("other", 280, 200, 0.82, 3)),
        face=SmileScript([True, True, False, True]),
        clock=clock,
        sink=store,
    )
    return SortingSession(sorter, store)


def run_session(session, pause_s=0.0):
    session.handle_text(START)
    while session.mode == "running":
        event = session.tick()
        if event is not None:
            print(json.dumps(event.to_dict(), ensure_ascii=False))
        if pause_s > 0:
            time.sleep(pause_s)


def main():
    parser = argparse.ArgumentParser(description="本机 mock 分拣演示")
    parser.add_argument("--web", action="store_true", help="同时启动局域网看板")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--pause", type=float, default=None, help="每轮间隔秒数；--web 默认 1.5")
    args = parser.parse_args()

    tick = {"now": 1000}

    def clock():
        tick["now"] += 100
        return tick["now"]

    store = EventStore(log_path=str(ROOT / "events.jsonl"))
    session = build_demo(clock, store)
    pause_s = args.pause if args.pause is not None else (1.5 if args.web else 0.0)

    if args.web:
        server = serve(args.host, args.port, store=store)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://{args.host}:{args.port}"
        print(f"看板已启动：{base}")
        print("页面：/  /events  /categories  /status")
        print("开始写入 mock 分拣事件…")
        try:
            run_session(session, pause_s=pause_s)
            print("演示结束，看板仍在运行。按 Ctrl+C 退出。")
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n已退出")
        finally:
            server.shutdown()
        return

    run_session(session, pause_s=pause_s)


if __name__ == "__main__":
    main()
