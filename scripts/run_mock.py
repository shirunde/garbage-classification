"""本机假数据演示：识别→抓取→记账。

用法：
  python3 scripts/run_mock.py           # 终端打印每一步
  python3 scripts/run_mock.py --web     # 同时打开样板看板
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

from control.demo_scenario import STEPS, build_demo
from control.voice import START
from dashboard.server import serve
from dashboard.store import EventStore
from shared.schemas import CLASS_LABELS, REASON_LABELS


def run_session(session, pause_s=0.0):
    session.handle_text(START)
    index = 0
    events = []
    while session.mode == "running":
        event = session.tick()
        if event is None:
            break
        step = STEPS[index] if index < len(STEPS) else "后续目标"
        index += 1
        payload = event.to_dict()
        payload["step"] = step
        events.append(event)
        cls_label = CLASS_LABELS.get(event.cls, event.cls or "-")
        reason_label = REASON_LABELS.get(event.reason, event.reason)
        print(f"[{step}] {cls_label} -> {reason_label}")
        print(json.dumps(event.to_dict(), ensure_ascii=False))
        if pause_s > 0:
            time.sleep(pause_s)
    return events


def main():
    parser = argparse.ArgumentParser(description="本机 mock 分拣演示")
    parser.add_argument("--web", action="store_true", help="同时启动局域网看板")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--pause", type=float, default=None, help="每轮间隔秒数；--web 默认 1.2")
    args = parser.parse_args()

    tick = {"now": 1000}

    def clock():
        tick["now"] += 100
        return tick["now"]

    store = EventStore(log_path=str(ROOT / "events.jsonl"))
    session = build_demo(clock, store)
    pause_s = args.pause if args.pause is not None else (1.2 if args.web else 0.0)

    if args.web:
        server = serve(args.host, args.port, store=store)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://{args.host}:{args.port}"
        print(f"样板看板：{base}")
        print("页面：/  /events  /categories  /status")
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
