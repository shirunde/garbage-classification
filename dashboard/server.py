"""局域网看板样板。四个页面读同一份 EventStore。"""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from shared.schemas import CLASS_LABELS, REASON_LABELS, Reason
from dashboard.store import EventStore

PAGES = {
    "/": "总览统计",
    "/events": "事件流水",
    "/categories": "类别分布",
    "/status": "系统与兜底状态",
}

FLOW = (
    ("采集", "相机或假 detect"),
    ("识别", "类别 / 像素 / 置信度"),
    ("确认", "灰区等笑脸，低置信度先颜色追踪"),
    ("抓取", "固定高度，失败重试 1 次"),
    ("投放", "按类别进 1～4 号箱"),
    ("记账", "写入 event 并刷新看板"),
)


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
                        "by_class": store.by_class(),
                        "fallback": store.fallback_counts(),
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
h1{font-size:22px;margin:0 0 8px}
.sub{color:#6b7280;margin:0 0 16px;font-size:14px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:12px;margin-bottom:16px}
.statbox{background:#f8fafc;border:1px solid #e5e7eb;border-radius:8px;padding:12px}
.statbox .n{font-size:28px;font-weight:700}
.statbox .k{color:#6b7280;font-size:13px}
.card{background:#fff;border:1px solid #e5e7eb;border-radius:8px;padding:16px;max-width:960px}
.pending{font-weight:600;color:#b45309}
table{border-collapse:collapse;width:100%}
th,td{border-bottom:1px solid #e5e7eb;text-align:left;padding:8px;font-size:14px}
th{color:#6b7280;font-weight:600}
.ok{color:#047857}.fail{color:#b91c1c}
.bar{background:#ccfbf1;height:10px;border-radius:6px;margin-top:6px}
.bar>span{display:block;height:10px;background:#0f766e;border-radius:6px}
.flow{display:flex;flex-wrap:wrap;gap:8px;margin:12px 0 0}
.step{background:#ecfeff;border:1px solid #99f6e4;border-radius:6px;padding:8px 10px;font-size:13px}
.hint{color:#6b7280;font-size:13px;margin-top:12px}
"""


def render_page(path, store):
    title = PAGES[path]
    nav = "".join(
        f'<a href="{href}">{name}</a>' for href, name in PAGES.items()
    )
    if path == "/":
        body = _render_home(store)
    elif path == "/events":
        body = _render_events(store)
    elif path == "/categories":
        body = _render_categories(store)
    else:
        body = _render_status(store)
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<meta http-equiv='refresh' content='2'>"
        f"<title>{title}</title><style>{STYLE}</style></head><body>"
        f"<nav>{nav}</nav><div class='card'><h1>{title}</h1>"
        "<p class='sub'>样板页，数据来自同一份 event。视觉和真臂接上后不用改字段。</p>"
        f"{body}</div></body></html>"
    )


def _render_home(store):
    summary = store.summary()
    total = summary["total"] or 1
    rate = round(100 * summary["success"] / total) if summary["total"] else 0
    last = store.events[-1] if store.events else None
    last_text = "暂无"
    if last:
        last_text = (
            f"{CLASS_LABELS.get(last['cls'], last['cls'] or '-')} · "
            f"{REASON_LABELS.get(last['reason'], last['reason'])}"
        )
    flow = "".join(
        f"<div class='step'><b>{name}</b><br>{detail}</div>" for name, detail in FLOW
    )
    return (
        "<div class='grid'>"
        f"<div class='statbox'><div class='k'>总次数</div><div class='n'>{summary['total']}</div></div>"
        f"<div class='statbox'><div class='k'>成功</div><div class='n'>{summary['success']}</div></div>"
        f"<div class='statbox'><div class='k'>失败</div><div class='n'>{summary['failed']}</div></div>"
        f"<div class='statbox'><div class='k'>成功率</div><div class='n'>{rate}%</div></div>"
        "</div>"
        f"<p>最近一次：{last_text}</p>"
        "<p>识别→抓取流程</p>"
        f"<div class='flow'>{flow}</div>"
        "<p class='hint'>本机运行 python3 scripts/run_mock.py --web 写入假事件。页面每 2 秒刷新。</p>"
    )


def _render_events(store):
    rows = "".join(_event_row(event) for event in reversed(store.events))
    return (
        "<table><tr><th>时间</th><th>类别</th><th>投放箱</th><th>结果</th><th>耗时(ms)</th><th>原因</th></tr>"
        + (rows or "<tr><td colspan='6'>暂无事件</td></tr>")
        + "</table>"
    )


def _render_categories(store):
    counts = store.by_class()
    total = max(sum(counts.values()), 1)
    blocks = []
    for name, count in counts.items():
        width = int(100 * count / total)
        blocks.append(
            f"<p>{CLASS_LABELS[name]}：{count}</p>"
            f"<div class='bar'><span style='width:{width}%'></span></div>"
        )
    return "".join(blocks)


def _render_status(store):
    pending = CLASS_LABELS.get(store.pending_cls, "无")
    rows = "".join(
        f"<tr><td>{reason}</td><td>{REASON_LABELS.get(reason, reason)}</td><td>{count}</td></tr>"
        for reason, count in store.fallback_counts().items()
    )
    return (
        f"<p class='pending'>待确认类别：{pending}</p>"
        "<table><tr><th>原因码</th><th>说明</th><th>次数</th></tr>"
        f"{rows}</table>"
        "<p class='hint'>通信异常后不再下发新运动，需人工恢复。</p>"
    )


def _event_row(event):
    label = CLASS_LABELS.get(event["cls"], event["cls"] or "-")
    result = "成功" if event["ok"] else "失败"
    result_class = "ok" if event["ok"] else "fail"
    reason = REASON_LABELS.get(event["reason"], event["reason"])
    bin_id = event.get("bin_id", 0)
    return (
        f"<tr><td>{event['ts']}</td><td>{label}</td><td>{bin_id or '-'}</td>"
        f"<td class='{result_class}'>{result}</td>"
        f"<td>{event['cost_ms']}</td><td>{reason}</td></tr>"
    )


def serve(host="0.0.0.0", port=8765, store=None):
    store = store or EventStore()
    server = ThreadingHTTPServer((host, port), make_handler(store))
    server.store = store
    return server
