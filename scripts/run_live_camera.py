"""Serve the board camera from loopback for sorting and dashboard preview."""

import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import cv2


def main():
    changed = threading.Condition()
    latest = None
    stop = threading.Event()

    def collect():
        nonlocal latest
        while not stop.is_set():
            camera = cv2.VideoCapture(0, cv2.CAP_V4L2)
            try:
                camera.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                camera.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                while camera.isOpened() and not stop.is_set():
                    ok, frame = camera.read()
                    if not ok or frame is None or frame.shape[:2] != (480, 640):
                        break
                    ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 92])
                    if ok:
                        with changed:
                            latest = (time.monotonic_ns(), encoded.tobytes())
                            changed.notify_all()
            finally:
                camera.release()
                with changed:
                    latest = None
            stop.wait(1)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            url = urlsplit(self.path)
            if url.path != "/frame.jpg":
                self.send_error(404)
                return
            try:
                after = int(parse_qs(url.query).get("after", ["0"])[0])
            except ValueError:
                self.send_error(400)
                return

            def fresh():
                return latest is not None and latest[0] > after and time.monotonic_ns() - latest[0] < 1_000_000_000

            with changed:
                frame = latest if changed.wait_for(fresh, timeout=1.2) else None
            if frame is None:
                self.send_error(503, "Camera frame unavailable")
                return
            sequence, jpeg = frame
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(jpeg)))
            self.send_header("X-Frame-Sequence", str(sequence))
            self.end_headers()
            try:
                self.wfile.write(jpeg)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, *args):
            pass

    with ThreadingHTTPServer(("127.0.0.1", 8767), Handler) as server:
        worker = threading.Thread(target=collect, daemon=True)
        worker.start()
        try:
            server.serve_forever()
        finally:
            stop.set()
            worker.join(timeout=2)


if __name__ == "__main__":
    main()
