import json
import subprocess
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch

from dashboard.server import serve
from dashboard.sort_job import FixedSortJob


class SortButtonTest(unittest.TestCase):
    def test_only_same_origin_can_start_and_second_request_cannot_queue(self):
        job = FixedSortJob("root@192.168.137.100", verify_placement=True)
        release = threading.Event()
        started = threading.Event()

        def fake_run(command, **options):
            started.set()
            release.wait(3)
            return subprocess.CompletedProcess(command, 0, stdout="落点核验通过，已提交分拣成功事件。")

        server = serve("127.0.0.1", 0, sort_job=job)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        origin = f"http://127.0.0.1:{server.server_port}"
        url = origin + "/api/fixed-sort"

        def start(request_origin):
            request = Request(url, b"{}", {"Origin": request_origin, "Content-Type": "application/json"})
            return urlopen(request, timeout=2)

        try:
            with patch("dashboard.sort_job.subprocess.run", side_effect=fake_run) as run:
                with self.assertRaises(HTTPError) as refused:
                    start("https://elsewhere.example")
                self.assertEqual(refused.exception.code, 403)
                with start(origin) as response:
                    self.assertEqual(response.status, 202)
                    self.assertEqual(json.load(response)["status"], "running")
                self.assertTrue(started.wait(2))
                with self.assertRaises(HTTPError) as duplicate:
                    start(origin)
                self.assertEqual(duplicate.exception.code, 409)
                self.assertIn("--qwen-verify", run.call_args.args[0][-1])
                run.assert_called_once()
                release.set()
        finally:
            release.set()
            server.shutdown()
            server.server_close()
        self.assertEqual(job.snapshot()["status"], "completed")
