"""Read fresh JPEG frames from the board camera service."""

from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener


LIVE_CAMERA_URL = "http://127.0.0.1:8767/frame.jpg"


def camera_source_if_running(cv2, index):
    if index != 0:
        return None
    last_frame = 0
    open_frame = build_opener(ProxyHandler({})).open

    def read():
        nonlocal last_frame
        with open_frame(f"{LIVE_CAMERA_URL}?after={last_frame}", timeout=2) as response:
            jpeg = response.read(640 * 480 * 3)
            sequence = int(response.headers["X-Frame-Sequence"])
        import numpy as np

        frame = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
        if frame is None or frame.shape[:2] != (480, 640):
            raise RuntimeError("直播相机未返回有效的 640×480 画面")
        last_frame = sequence
        return frame

    try:
        first = read()
    except URLError as exc:
        if isinstance(exc.reason, ConnectionRefusedError):
            return None
        raise

    def source():
        nonlocal first
        if first is not None:
            frame, first = first, None
            return frame
        return read()

    return source
