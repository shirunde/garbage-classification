"""Run the real event/recovery pipeline using simulated hardware only."""

import argparse
import threading
import time
import uuid
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from control.arm import CommError
from control.fixed_runner import FixedRunner, VerifiedGraspFailure
from dashboard.server import serve
from dashboard.store import EventStore
from scripts.run_dashboard import load_history
from shared.event_sink import EventSink
from shared.schemas import DetectResult


class DemoDetector:
    def __init__(self, confidence=.9, empty=False):
        self.confidence, self.empty = confidence, empty

    def detect(self):
        return None if self.empty else DetectResult('other', 300, 400, self.confidence, time.time_ns()//1000000)


class DemoArm:
    def __init__(self, empty_grasps=0, communication_error=False):
        self.empty_grasps = empty_grasps
        self.communication_error = communication_error

    def grasp(self, target):
        if self.communication_error:
            raise CommError('模拟 I2C 故障')
        if self.empty_grasps:
            self.empty_grasps -= 1
            raise VerifiedGraspFailure('模拟反馈：已确认空夹，可安全重试')
        return True

    def go_safe(self):
        print('模拟回安全位')

    def _move(self, *args):
        pass


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8766)
    parser.add_argument('--exit-after-demo', action='store_true')
    args = parser.parse_args(argv)
    # Separate demo runs: do not mix different preview sessions or outboxes.
    folder = ROOT/'records'/'offline-demo'/uuid.uuid4().hex
    folder.mkdir(parents=True, exist_ok=True)
    log = folder/'dashboard.jsonl'
    store = EventStore(log_path=str(log))
    load_history(log, store)
    server = serve(args.host, args.port, store=store, data_source='mock')
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    local = '127.0.0.1' if args.host == '0.0.0.0' else args.host
    url = f'http://{local}:{server.server_address[1]}'
    sink = EventSink(folder/'producer', url)
    try:
        scenarios = [
            ('命令完成但未核验', DemoDetector(), DemoArm()),
            ('低置信度跳过', DemoDetector(.4), DemoArm()),
            ('无目标超时', DemoDetector(empty=True), DemoArm()),
            ('空夹两次后回安全位', DemoDetector(), DemoArm(empty_grasps=2)),
            ('通信错误后停止', DemoDetector(), DemoArm(communication_error=True)),
        ]
        for name, detector, arm in scenarios:
            runner = FixedRunner(detector, arm, sink)
            result = runner.run_once(timeout_sec=.2)
            print(name + ': ' + result['event']['reason'])
        print(f'离线兜底看板：{url} （全部是模拟事件，不代表真机结果）', flush=True)
        if not args.exit_after_demo:
            while True:
                time.sleep(.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


if __name__ == '__main__':
    main()
