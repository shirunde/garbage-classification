import base64
import io
import json
import threading
import unittest
from unittest.mock import Mock
from urllib.request import Request, urlopen

from dashboard.placement_model import QwenPlacementVerifier
from dashboard.server import serve


class PlacementModelTest(unittest.TestCase):
    def test_dashboard_relay_uses_qwen_image_request_and_checks_reply(self):
        verifier = QwenPlacementVerifier("https://example.test/compatible-mode/v1", "test-only")
        vendor_reply = {"choices": [{"message": {"content": '{"status":"in_bin"}'}}]}
        verifier.open = Mock(return_value=io.BytesIO(json.dumps(vendor_reply).encode()))
        server = serve("127.0.0.1", 0, placement_verifier=verifier)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            image = base64.b64encode(b"\xff\xd8test\xff\xd9").decode()
            request = Request(
                f"http://127.0.0.1:{server.server_port}/api/placement/verify",
                data=json.dumps({"category": "other", "image_jpeg": image}).encode(),
                headers={"Content-Type": "application/json"},
            )
            with urlopen(request, timeout=2) as response:
                self.assertEqual(json.load(response), {"status": "in_bin"})
            sent = verifier.open.call_args.args[0]
            self.assertEqual(sent.full_url, "https://example.test/compatible-mode/v1/chat/completions")
            wire = json.loads(sent.data)
            self.assertEqual(wire["model"], "qwen3.8-max")
            self.assertEqual(wire["messages"][0]["content"][1]["image_url"]["url"],
                             "data:image/jpeg;base64," + image)
        finally:
            server.shutdown()
            server.server_close()

    def test_unexpected_answer_stays_uncertain(self):
        verifier = QwenPlacementVerifier("https://example.test/v1", "test-only")
        verifier.open = Mock(return_value=io.BytesIO(
            b'{"choices":[{"message":{"content":"The image probably looks right."}}]}',
        ))
        payload = {"category": "other", "image_jpeg": base64.b64encode(b"\xff\xd8test\xff\xd9").decode()}
        self.assertEqual(verifier.verify(payload), "uncertain")
