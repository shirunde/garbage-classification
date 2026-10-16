"""局域网看板。四个页面：总览、事件流水、类别分布、兜底状态。"""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from shared.schemas import CLASS_LABELS, Reason
from dashboard.store import EventStore

PAGES = {
    "/": "总览统计",
    "/events": "事件流水",
    "/categories": "类别分布",
    "/status": "系统与兜底状态",
}


def make_handler(store):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            path = urlparse(self.path).path
            if path == "/api/events":
                self._send_json({"events": store.events, "summary": store.summary()})
                return
            if path not in PAGES:
                self._send_text("页面不存在", 404)
                return
            self._send_html(render_page(path, store))

        def do_POST(self):
            path = urlparse(self.path).path
            if path != "/api/events":
                self._send_text("不支持的接口", 404)
                return
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length)
            try:
                saved = store.add(json.loads(raw.decode("utf-8")))
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                self._send_json({"error": str(exc)}, 400)
                return
            self._send_json(saved, 201)

        def log_message(self, fmt, *args):
            return

        def _send_json(self, payload, status=200):
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_html(self, text, status=200):
            body = text.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_text(self, text, status):
            body = text.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return Handler


def render_page(path, store):
    title = PAGES[path]
    nav = "".join(
        f'<a href="{href}">{name}</a>' for href, name in PAGES.items()
    )
    if path == "/":
        summary = store.summary()
        body = (
            f"<p>总次数 {summary['total']}</p>"
            f"<p>成功 {summary['success']}</p>"
            f"<p>失败 {summary['failed']}</p>"
        )
    elif path == "/events":
        rows = "".join(_event_row(event) for event in reversed(store.events))
        body = "<table><tr><th>时间</th><th>类别</th><th>结果</th><th>耗时</th><th>原因</th></tr>" + rows + "</table>"
    elif path == "/categories":
        body = "".join(
            f"<p>{CLASS_LABELS[name]}：{count}</p>"
            for name, count in store.by_class().items()
        )
    else:
        body = "".join(
            f"<p>{reason}：{count}</p>"
            for reason, count in store.fallback_counts().items()
        )
    return (
        "<!doctype html><meta charset='utf-8'>"
        f"<title>{title}</title><nav>{nav}</nav><h1>{title}</h1>{body}"
    )


def _event_row(event):
    label = CLASS_LABELS.get(event["cls"], event["cls"] or "-")
    result = "成功" if event["ok"] else "失败"
    reason = event["reason"] if event["reason"] in Reason.ALL else event["reason"]
    return (
        f"<tr><td>{event['ts']}</td><td>{label}</td><td>{result}</td>"
        f"<td>{event['cost_ms']}</td><td>{reason}</td></tr>"
    )


def serve(host="0.0.0.0", port=8765, store=None):
    store = store or EventStore()
    server = ThreadingHTTPServer((host, port), make_handler(store))
    server.store = store
    return server
