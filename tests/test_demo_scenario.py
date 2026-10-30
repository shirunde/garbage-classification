import json
import threading
import unittest
import urllib.request

from control.demo_scenario import EXPECTED_REASONS, STEPS, build_demo
from control.voice import START
from dashboard.server import serve
from dashboard.store import EventStore
from shared.schemas import REASON_LABELS, Reason


class Clock:
    def __init__(self):
        self.now = 1000

    def __call__(self):
        self.now += 50
        return self.now


class DemoScenarioTest(unittest.TestCase):
    def test_mock_loop_covers_main_and_fallback_reasons(self):
        store = EventStore()
        session = build_demo(Clock(), store)
        session.handle_text(START)
        reasons = []
        while session.mode == "running":
            event = session.tick()
            if event is None:
                break
            reasons.append(event.reason)
        self.assertEqual(tuple(reasons), EXPECTED_REASONS)
        self.assertEqual(len(STEPS), len(EXPECTED_REASONS))
        self.assertEqual(session.mode, "idle")
        self.assertEqual(store.summary()["success"], 3)
        self.assertEqual(store.fallback_counts()[Reason.GRASP_FAIL], 1)

    def test_sample_pages_show_chinese_labels(self):
        store = EventStore()
        session = build_demo(Clock(), store)
        session.handle_text(START)
        while session.mode == "running":
            session.tick()

        server = serve("127.0.0.1", 0, store=store)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.shutdown)
        port = server.server_address[1]
        base = f"http://127.0.0.1:{port}"

        with urllib.request.urlopen(base + "/", timeout=2) as response:
            home = response.read().decode("utf-8")
        self.assertIn("识别→抓取流程", home)
        self.assertIn("成功率", home)

        with urllib.request.urlopen(base + "/events", timeout=2) as response:
            events = response.read().decode("utf-8")
        self.assertIn(REASON_LABELS[Reason.NEED_CONFIRM_TIMEOUT], events)
        self.assertIn("可回收物", events)

        with urllib.request.urlopen(base + "/status", timeout=2) as response:
            status = response.read().decode("utf-8")
        self.assertIn("待确认类别", status)
        self.assertIn(REASON_LABELS[Reason.GRASP_FAIL], status)

        with urllib.request.urlopen(base + "/api/events", timeout=2) as response:
            payload = json.loads(response.read().decode("utf-8"))
        self.assertEqual(len(payload["events"]), len(EXPECTED_REASONS))
        self.assertIn("by_class", payload)


if __name__ == "__main__":
    unittest.main()
