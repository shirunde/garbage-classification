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
                self._send_json(
                    {
                        "events": store.events,
                        "summary": store.summary(),
                        "pending_cls": store.pending_cls,
                    }
                )
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


STYLE = """
body{font-family:Segoe UI,Helvetica,Arial,sans-serif;margin:24px;background:#f6f7f9;color:#1f2937}
nav{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:16px}
nav a{color:#0f766e;text-decoration:none;padding:6px 10px;background:#fff;border:1px solid #d1d5db;border-radius:6px}
nav a:hover{background:#ecfeff}
h1{font-size:22px;margin:0 0 16px}
.card{background:#fff;border:1px solid #e5e7eb;border-radius:8px;padding:16px;max-width:880px}
.stat{font-size:18px;margin:8px 0}
.pending{font-weight:600;color:#b45309}
table{border-collapse:collapse;width:100%}
th,td{border-bottom:1px solid #e5e7eb;text-align:left;padding:8px;font-size:14px}
th{color:#6b7280;font-weight:600}
.ok{color:#047857}.fail{color:#b91c1c}
.hint{color:#6b7280;font-size:13px;margin-top:12px}
"""


def render_page(path, store):
    title = PAGES[path]
    nav = "".join(
        f'<a href="{href}">{name}</a>' for href, name in PAGES.items()
    )
    if path == "/":
        summary = store.summary()
        body = (
            f"<p class='stat'>总次数 {summary['total']}</p>"
            f"<p class='stat'>成功 {summary['success']}</p>"
            f"<p class='stat'>失败 {summary['failed']}</p>"
            "<p class='hint'>页面每 2 秒自动刷新，便于本机 mock 演示。</p>"
        )
    elif path == "/events":
        rows = "".join(_event_row(event) for event in reversed(store.events))
        body = (
            "<table><tr><th>时间</th><th>类别</th><th>结果</th><th>耗时(ms)</th><th>原因</th></tr>"
            + (rows or "<tr><td colspan='5'>暂无事件</td></tr>")
            + "</table>"
        )
    elif path == "/categories":
        body = "".join(
            f"<p class='stat'>{CLASS_LABELS[name]}：{count}</p>"
            for name, count in store.by_class().items()
        )
    else:
        pending = CLASS_LABELS.get(store.pending_cls, "无")
        counts = "".join(
            f"<p>{reason}：{count}</p>"
            for reason, count in store.fallback_counts().items()
        )
        body = f"<p class='pending'>待确认类别：{pending}</p>{counts}"
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<meta http-equiv='refresh' content='2'>"
        f"<title>{title}</title><style>{STYLE}</style></head><body>"
        f"<nav>{nav}</nav><div class='card'><h1>{title}</h1>{body}</div>"
        "</body></html>"
    )


def _event_row(event):
    label = CLASS_LABELS.get(event["cls"], event["cls"] or "-")
    result = "成功" if event["ok"] else "失败"
    result_class = "ok" if event["ok"] else "fail"
    reason = event["reason"] if event["reason"] in Reason.ALL else event["reason"]
    return (
        f"<tr><td>{event['ts']}</td><td>{label}</td>"
        f"<td class='{result_class}'>{result}</td>"
        f"<td>{event['cost_ms']}</td><td>{reason}</td></tr>"
    )


def serve(host="0.0.0.0", port=8765, store=None):
    store = store or EventStore()
    server = ThreadingHTTPServer((host, port), make_handler(store))
    server.store = store
    return server
