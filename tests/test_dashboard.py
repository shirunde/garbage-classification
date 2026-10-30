import json
import tempfile
import threading
import unittest
import urllib.request

from dashboard.server import serve
from dashboard.store import EventStore
from shared.schemas import Reason, SortEvent


def sample_event():
    return SortEvent("1", 1100, "other", 4, True, 80, Reason.OK)


class DashboardTest(unittest.TestCase):
    def test_four_pages_show_posted_event(self):
        server = serve("127.0.0.1", 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.shutdown)
        port = server.server_address[1]
        base = f"http://127.0.0.1:{port}"

        payload = json.dumps(sample_event().to_dict()).encode("utf-8")
        request = urllib.request.Request(base + "/api/events", data=payload)
        with urllib.request.urlopen(request, timeout=2) as response:
            self.assertEqual(response.status, 201)

        for path in ("/", "/events", "/categories", "/status"):
            with urllib.request.urlopen(base + path, timeout=2) as response:
                page = response.read().decode("utf-8")
            self.assertEqual(response.status, 200)
            self.assertIn("<h1>", page)

        with urllib.request.urlopen(base + "/events", timeout=2) as response:
            page = response.read().decode("utf-8")
        self.assertIn("其他垃圾", page)
        self.assertIn("分拣成功", page)
        self.assertEqual(server.store.summary()["success"], 1)

    def test_pending_class_is_visible_and_events_are_logged(self):
        with tempfile.TemporaryDirectory() as directory:
            store = EventStore(log_path=directory + "/events.jsonl")
            store.show_pending("hazardous")
            self.assertEqual(store.pending_cls, "hazardous")
            store.publish(sample_event())
            with open(store.log_path, encoding="utf-8") as log_file:
                saved = json.loads(log_file.read().strip())
            self.assertEqual(saved["reason"], Reason.OK)


if __name__ == "__main__":
    unittest.main()
