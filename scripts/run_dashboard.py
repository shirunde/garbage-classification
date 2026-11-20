"""Run the dashboard for board sorting events, restoring history from JSONL."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dashboard.server import serve
from dashboard.placement_model import QwenPlacementVerifier
from dashboard.sort_job import FixedSortJob
from dashboard.store import EventStore
from shared.schemas import SortEvent


def load_history(path: Path, store: EventStore) -> None:
    if not path.is_file():
        return
    with path.open("r", encoding="utf-8") as source:
        for line_number, line in enumerate(source, 1):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
                event = SortEvent(**payload)
                store.restore(event)
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                print(f"跳过无效历史事件，第 {line_number} 行: {exc}", file=sys.stderr)
                continue


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--event-log", default=str(ROOT / "events.jsonl"))
    parser.add_argument("--camera-url", help="板端相机 JPEG 地址，可通过 SSH 转发到本机")
    parser.add_argument("--qwen-base-url", default=os.environ.get("QWEN_BASE_URL"))
    parser.add_argument("--qwen-model", default="qwen3.8-max")
    parser.add_argument("--enable-fixed-sort", action="store_true", help="在本机看板启用主板固定点分拣按钮")
    args = parser.parse_args()

    verifier = None
    if args.qwen_base_url:
        key = (os.environ.get("QIANWEN_API_KEY") or os.environ.get("QWEN_API_KEY")
               or os.environ.get("DASHSCOPE_API_KEY"))
        if not key or args.host != "127.0.0.1":
            parser.error("千问核验需要 API Key 环境变量和本机回环监听 --host 127.0.0.1")
        verifier = QwenPlacementVerifier(args.qwen_base_url, key, args.qwen_model)
    if args.enable_fixed_sort and args.host != "127.0.0.1":
        parser.error("分拣按钮要求 --host 127.0.0.1")
    sort_job = FixedSortJob("root@192.168.137.100", verify_placement=verifier is not None) if args.enable_fixed_sort else None
    log_path = Path(args.event_log)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    store = EventStore(log_path=str(log_path))
    load_history(log_path, store)
    server = serve(args.host, args.port, store=store, data_source="board", camera_url=args.camera_url,
                   placement_verifier=verifier, sort_job=sort_job)
    display_host = args.host if args.host not in ("0.0.0.0", "::") else "<板卡IP>"
    print(f"看板已启动，浏览器访问: http://{display_host}:{args.port}")
    print(f"历史日志: {log_path}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n看板已停止")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
