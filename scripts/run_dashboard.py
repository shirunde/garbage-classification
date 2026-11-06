"""Run the dashboard for board sorting events, restoring history from JSONL."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dashboard.server import serve
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
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                print(f"跳过无效历史事件，第 {line_number} 行: {exc}", file=sys.stderr)
                continue
            store.events.append(event.to_dict())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--event-log", default=str(ROOT / "events.jsonl"))
    args = parser.parse_args()

    log_path = Path(args.event_log)
    store = EventStore()
    load_history(log_path, store)
    server = serve(args.host, args.port, store=store, data_source="board")
    print(f"看板已启动: http://{args.host}:{args.port}")
    print(f"历史日志: {log_path}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n看板已停止")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
