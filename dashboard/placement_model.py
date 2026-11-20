"""Qwen visual verification of a single cropped placement photo."""

import base64
import binascii
import json
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from shared.schemas import CLASS_LABELS


BIN_COLORS = {"recyclable": "蓝色", "hazardous": "红色", "kitchen": "绿色", "other": "黄色"}
PLACEMENT_STATUSES = {"in_bin", "not_in_bin", "uncertain"}
MAX_REQUEST_BYTES = 512 * 1024


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        return None


class QwenPlacementVerifier:
    def __init__(self, base_url, key, model="qwen3.8-max"):
        url = urlsplit(base_url)
        if url.scheme != "https" or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ValueError("千问 Base URL 必须是无凭据的 HTTPS 接口地址")
        self.url = base_url.rstrip("/") + "/chat/completions"
        self.key = key
        self.model = model
        self.open = build_opener(NoRedirect()).open

    def verify(self, payload):
        if not isinstance(payload, dict) or set(payload) != {"category", "image_jpeg"}:
            raise ValueError("落点核验参数无效")
        category = payload["category"]
        image = payload["image_jpeg"]
        if not isinstance(category, str) or category not in BIN_COLORS or not isinstance(image, str):
            raise ValueError("落点类别或图像无效")
        try:
            jpeg = base64.b64decode(image, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ValueError("落点图片 Base64 无效") from exc
        if not jpeg.startswith(b"\xff\xd8") or not jpeg.endswith(b"\xff\xd9"):
            raise ValueError("落点图片必须为 JPEG")

        prompt = (
            f"图片是机械臂松爪后拍摄的目标格裁图。目标为{BIN_COLORS[category]}{CLASS_LABELS[category]}格。"
            "判断是否有真实的立体积木落在该格的标记内。地垫上平面的彩色印刷标记本身不是积木。"
            "只有看见积木边缘、侧面等立体证据且其落点在格内才报 in_bin。"
            "格内清晰可见且没有实物才报 not_in_bin。遮挡、画面不完整、无法区分平面印刷或实物时报 uncertain。"
            '只返回 JSON 对象，格式为 {"status":"in_bin"}，status 也可为 not_in_bin 或 uncertain。'
        )
        body = {
            "model": self.model,
            "enable_thinking": False,
            "max_tokens": 128,
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + image}},
            ]}],
        }
        request = Request(self.url, data=json.dumps(body).encode(), method="POST", headers={
            "Authorization": "Bearer " + self.key,
            "Content-Type": "application/json",
        })
        with self.open(request, timeout=12) as response:
            reply = json.loads(response.read(1024 * 1024))
        content = reply["choices"][0]["message"]["content"]
        if not isinstance(content, str):
            return "uncertain"
        content = content.strip()
        if content.startswith("```json") and content.endswith("```"):
            content = content[7:-3].strip()
        try:
            result = json.loads(content)
        except ValueError:
            return "uncertain"
        status = result.get("status") if isinstance(result, dict) and set(result) == {"status"} else None
        return status if isinstance(status, str) and status in PLACEMENT_STATUSES else "uncertain"
