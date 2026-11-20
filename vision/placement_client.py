"""Send only the calibrated target-bin crop through the dashboard tunnel."""

import base64
import json
from urllib.request import ProxyHandler, Request, build_opener


BIN_CROPS = {
    "recyclable": (240, 190, 545, 480),
    "hazardous": (0, 131, 182, 286),
    "kitchen": (0, 190, 230, 480),
    "other": (340, 145, 540, 305),
}


def verify_placement(cv2, dashboard_url, category, image_path):
    image = cv2.imread(image_path)
    if image is None or image.shape[:2] != (480, 640):
        raise ValueError("落点照片必须为 640×480")
    left, top, right, bottom = BIN_CROPS[category]
    ok, jpeg = cv2.imencode(".jpg", image[top:bottom, left:right])
    if not ok:
        raise ValueError("无法编码目标格裁图")
    body = json.dumps({"category": category, "image_jpeg": base64.b64encode(jpeg.tobytes()).decode("ascii")})
    request = Request(dashboard_url.rstrip("/") + "/api/placement/verify", data=body.encode(), method="POST",
                      headers={"Content-Type": "application/json"})
    with build_opener(ProxyHandler({})).open(request, timeout=15) as response:
        result = json.loads(response.read(4096))
    return result["status"]
