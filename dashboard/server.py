"""垃圾分拣看板。首屏服务端渲染，后续通过现有事件接口局部更新。"""

import json
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from dashboard.store import EventStore
from shared.schemas import CLASS_LABELS, REASON_LABELS, Reason

PAGES = {"/": "总览统计", "/events": "事件流水", "/categories": "类别分布", "/status": "系统状态"}
DESCRIPTIONS = {
    "/": "从识别到投放，每一次分拣都有迹可循。",
    "/events": "查看每一条事件，追踪分类结果与异常原因。",
    "/categories": "了解四类垃圾的事件分布与成功记录。",
    "/status": "关注待确认目标、异常记录与数据连接。",
}
FLOW = (("采集", "获取目标图像"), ("识别", "判断类别与位置"), ("确认", "处理低置信度目标"),
        ("抓取", "失败最多重试一次"), ("投放", "移动至分类区域"), ("记录", "保存分拣结果"))
STATIC_FILES = {
    "/static/dashboard.css": ("dashboard.css", "text/css; charset=utf-8"),
    "/static/dashboard.js": ("dashboard.js", "text/javascript; charset=utf-8"),
}
STATIC_ROOT = Path(__file__).with_name("static")


def icon(name, size=20):
    paths = {
        "home": '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
        "events": '<path d="M8 5h12M8 12h12M8 19h12"/><path d="M3 5h.01M3 12h.01M3 19h.01"/>',
        "chart": '<path d="M4 20h16M6 16v-5M12 16V4M18 16V8"/>',
        "status": '<path d="M2 12h5l3-8 4 16 3-8h5"/>',
        "arrow": '<path d="m5 12 14 0m-5-5 5 5-5 5"/>',
        "check": '<path d="m5 12 4 4L19 6"/>',
        "refresh": '<path d="M20 7v5h-5M4 17v-5h5"/><path d="M6 7a7 7 0 0 1 12-1l2 3M4 15l2 3a7 7 0 0 0 12-1"/>',
        "alert": '<path d="M10.3 4.2 2.5 18a1.5 1.5 0 0 0 1.3 2.2h16.4a1.5 1.5 0 0 0 1.3-2.2L13.7 4.2a2 2 0 0 0-3.4 0Z"/><path d="M12 9v4m0 3h.01"/>',
        "box": '<path d="m12 3 9 5-9 5-9-5 9-5Zm-9 5v9l9 5 9-5V8M12 13v9M7.5 5.5l9 5"/>',
    }
    return (f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" '
            'stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" '
            f'aria-hidden="true">{paths.get(name, paths["box"])}</svg>')


def safe_json(payload):
    return (json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c")
            .replace(">", "\\u003e").replace("&", "\\u0026"))


def make_handler(store, data_source=None):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            path = urlparse(self.path).path
            if path == "/api/events":
                self._send_json(store.snapshot())
            elif path in STATIC_FILES:
                filename, mime = STATIC_FILES[path]
                self._send((STATIC_ROOT / filename).read_bytes(), mime)
            elif path in PAGES:
                self._send_html(render_page(path, store, data_source))
            else:
                self._send_text("页面不存在", 404)

        def do_POST(self):
            if urlparse(self.path).path != "/api/events":
                self._send_text("不支持的接口", 404)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length < 0:
                    raise ValueError("Content-Length 必须非负")
                raw = self.rfile.read(length)
                saved = store.add(json.loads(raw.decode("utf-8")))
            except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
                self._send_json({"error": str(exc)}, 400)
                return
            self._send_json(saved, 201)

        def log_message(self, fmt, *args):
            return

        def _send(self, body, mime, status=200):
            self.send_response(status)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def _send_json(self, payload, status=200):
            self._send(json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                       "application/json; charset=utf-8", status)

        def _send_html(self, text, status=200):
            self._send(text.encode("utf-8"), "text/html; charset=utf-8", status)

        def _send_text(self, text, status):
            self._send(text.encode("utf-8"), "text/plain; charset=utf-8", status)

    return Handler


def panel(title, content, subtitle="", action="", extra=""):
    sub = f'<p class="panel-subtitle">{subtitle}</p>' if subtitle else ""
    return (f'<section class="panel {extra}"><div class="panel-heading"><div><h2>{title}</h2>{sub}</div>'
            f'{action}</div>{content}</section>')


def event_row(event):
    cls = event["cls"]
    label = escape(str(CLASS_LABELS.get(cls, cls or "无目标")))
    index = list(CLASS_LABELS).index(cls) if cls in CLASS_LABELS else 4
    ok = bool(event["ok"])
    badge = "success" if ok else ("neutral" if event["reason"] == Reason.TIMEOUT_NO_TARGET else "failure")
    result = "成功" if ok else ("无目标" if badge == "neutral" else "未成功")
    reason = escape(str(REASON_LABELS.get(event["reason"], event["reason"])))
    return (f'<tr><td class="event-id">#{escape(str(event["event_id"]))}</td>'
            f'<td class="time-cell" data-ts="{escape(str(event["ts"]), quote=True)}">时标 {escape(str(event["ts"]))}</td>'
            f'<td><span class="class-label"><i class="class-dot class-{index}"></i>{label}</span></td>'
            f'<td>{escape(str(event["bin_id"])) + " 号箱" if event["bin_id"] else "—"}</td>'
            f'<td><span class="badge {badge}">{result}</span></td>'
            f'<td class="numeric">{escape(str(event["cost_ms"]))}<span class="unit"> ms</span></td>'
            f'<td class="reason-cell">{reason}</td></tr>')


def event_table(events, limit=10):
    rows = "".join(event_row(event) for event in list(reversed(events))[:limit])
    if not rows:
        rows = '<tr><td colspan="7"><div class="empty-state">' + icon("box", 32) + '<strong>暂无事件</strong><span>收到分拣记录后，会显示在这里。</span></div></td></tr>'
    return ('<div class="table-scroll"><table><thead><tr><th>事件编号</th><th>时间 / 时标</th><th>类别</th>'
            '<th>投放箱</th><th>结果</th><th>耗时</th><th>原因</th></tr></thead>'
            f'<tbody id="event-rows">{rows}</tbody></table></div>')


def category_bars(data):
    total = sum(data["by_class"].values())
    return "".join(
        f'<div class="category-row"><div class="category-line"><span class="class-label"><i class="class-dot class-{i}"></i>{escape(label)}</span>'
        f'<span><b>{data["by_class"].get(name, 0)}</b><small> 条</small></span></div>'
        f'<div class="bar-track"><span class="class-bg-{i}" style="width:{100 * data["by_class"].get(name, 0) / max(total, 1):.2f}%"></span></div></div>'
        for i, (name, label) in enumerate(CLASS_LABELS.items()))


def pending_content(data):
    pending = data["pending_cls"]
    label = escape(str(CLASS_LABELS.get(pending, pending or "")))
    if pending:
        return (f'<div class="pending-visual waiting">{icon("alert", 28)}</div><p class="eyebrow">等待表情确认</p>'
                f'<h3>{label}</h3><p class="muted">请在规定时间内确认当前目标，超时后将跳过。</p>')
    return (f'<div class="pending-visual">{icon("check", 28)}</div><p class="eyebrow">待确认类别</p>'
            '<h3>当前无待确认目标</h3><p class="muted">需要确认时，目标类别会显示在这里。</p>')


def metric_cards(data):
    s = data["summary"]
    rate = round(100 * s["success"] / s["total"]) if s["total"] else None
    cards = (("事件总数", "total", s["total"], "包含无目标及异常事件", "events"),
             ("成功事件", "success", s["success"], "已报告分拣成功的记录", "check"),
             ("未成功事件", "failed", s["failed"], "含跳过、无目标及动作失败", "alert"),
             ("事件成功率", "rate", str(rate) + "%" if rate is not None else "—", "成功事件 ÷ 全部事件", "chart"))
    return '<div class="metrics">' + "".join(
        f'<article class="metric"><div class="metric-top"><span>{label}</span><span class="metric-icon">{icon(symbol)}</span></div>'
        f'<div class="metric-value" data-metric="{key}">{value}</div><p>{hint}</p></article>'
        for label, key, value, hint, symbol in cards) + '</div>'


def home_page(data):
    latest = panel("最近事件", event_table(data["events"], 5), "按接收顺序显示最近 5 条记录",
                   '<a class="text-link" href="/events">查看全部 ' + icon("arrow", 16) + '</a>')
    pending = panel("目标确认", '<div id="pending-content" class="pending-content">' + pending_content(data) + '</div>')
    flow = '<div class="flow">' + "".join(
        f'<div class="flow-step"><span>{i:02}</span><strong>{name}</strong><small>{desc}</small></div>'
        for i, (name, desc) in enumerate(FLOW, 1)) + '</div>'
    categories = panel("类别概览", '<div id="category-bars">' + category_bars(data) + '</div>', "统计包含成功和未成功的类别事件")
    return metric_cards(data) + '<div class="overview-grid">' + latest + pending + '</div><div class="bottom-grid">' + panel("识别→抓取流程", flow, "流程说明，实时结果以事件记录为准") + categories + '</div>'


def events_page(data):
    options = "".join(f'<option value="{escape(name)}">{escape(label)}</option>' for name, label in CLASS_LABELS.items())
    reasons = "".join(f'<option value="{escape(name)}">{escape(label)}</option>' for name, label in REASON_LABELS.items())
    filters = (f'<form id="filters" class="filters" role="search"><label>类别<select id="class-filter"><option value="">全部类别</option>{options}<option value="__none">无目标</option></select></label>'
               '<label>结果<select id="result-filter"><option value="">全部结果</option><option value="success">成功</option><option value="failed">未成功</option></select></label>'
               f'<label>原因<select id="reason-filter"><option value="">全部原因</option>{reasons}</select></label>'
               '<label class="search-label">搜索<input id="event-search" type="search" placeholder="编号、类别或原因" autocomplete="off"></label>'
               '<button class="button subtle" type="reset">重置</button></form>')
    pager = ('<div class="pagination"><span id="result-count">共 ' + str(len(data["events"])) + ' 条事件</span>'
             '<div class="pager-controls"><label>每页<select id="page-size"><option>10</option><option>20</option><option>50</option></select></label>'
             '<button id="previous-page" class="button subtle" type="button" disabled>上一页</button>'
             '<span id="page-label">第 1 页</span><button id="next-page" class="button subtle" type="button">下一页</button></div></div>')
    return panel("全部事件", filters + event_table(data["events"]) + pager,
                 "筛选条件在自动更新时保持不变；无目标事件不会产生投放箱编号。")


def categories_page(data):
    cards = "".join(
        f'<article class="category-card"><span class="category-icon class-bg-{i}">{icon("box", 24)}</span><p>{escape(label)}</p>'
        f'<strong data-class-count="{escape(name)}">{data["by_class"].get(name, 0)}</strong><span class="muted"> 条事件</span>'
        f'<div class="category-card-footer">其中成功 <b data-class-success="{escape(name)}">{sum(1 for e in data["events"] if e["cls"] == name and e["ok"])}</b> 条</div></article>'
        for i, (name, label) in enumerate(CLASS_LABELS.items()))
    return ('<div class="category-cards">' + cards + '</div>' + panel("类别事件占比", '<div id="category-bars">' + category_bars(data) + '</div>',
            "以有类别的事件为统计范围；包含未成功记录，不等于实际投放数量。") +
            '<div class="info-note">' + icon("box") + '<span>无目标事件单独记录在事件流水中，不计入四类占比。</span></div>')


def status_page(data):
    pending = panel("待确认类别", '<div id="pending-content" class="pending-content">' + pending_content(data) + '</div>')
    device = panel("连接与设备", '<dl class="device-list"><div><dt>事件接口</dt><dd id="device-api-state">正在检查</dd></div>'
                   '<div><dt>自动更新间隔</dt><dd>2 秒</dd></div><div><dt>机械臂状态</dt><dd class="muted">暂未提供</dd></div>'
                   '<div><dt>摄像头状态</dt><dd class="muted">暂未提供</dd></div></dl><p class="small-note">接口连接正常仅表示数据可以读取，不代表硬件已连接。</p>')
    rows = "".join(f'<tr><td><span class="reason-icon">{icon("alert", 16)}</span>{escape(label)}</td><td class="code-cell">{escape(reason)}</td>'
                   f'<td class="numeric" data-reason-count="{escape(reason)}">{data["fallback"].get(reason, 0)}</td></tr>'
                   for reason, label in REASON_LABELS.items() if reason != Reason.OK)
    fallback = '<div class="table-scroll"><table><thead><tr><th>事件原因</th><th>原因码</th><th>累计次数</th></tr></thead><tbody>' + rows + '</tbody></table></div>'
    return ('<div class="status-grid">' + pending + device + '</div>' +
            '<div id="latest-alert" class="info-note">异常计数是历史累计值，当前状态请以设备实际情况为准。</div>' +
            panel("异常与兜底记录", fallback, "用于排查确认超时、抓取失败和通信异常。"))


def render_page(path, store, data_source=None):
    data = store.snapshot()
    title = PAGES[path]
    nav_icons = ("home", "events", "chart", "status")
    nav = "".join(f'<a href="{href}" class="nav-link{" active" if href == path else ""}"' +
                  (' aria-current="page"' if href == path else '') + f'>{icon(symbol)}<span>{name}</span></a>'
                  for (href, name), symbol in zip(PAGES.items(), nav_icons))
    renderer = {"/": home_page, "/events": events_page, "/categories": categories_page, "/status": status_page}[path]
    source_label = "模拟演示" if data_source == "mock" else "事件数据"
    bootstrap = safe_json({"data": data, "config": {"classes": CLASS_LABELS, "reasons": REASON_LABELS, "page": path}})
    return (
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
        f'<title>{title} · 循分工作台</title><link rel="stylesheet" href="/static/dashboard.css"><script defer src="/static/dashboard.js"></script></head>'
        '<body><a href="#main-content" class="skip-link">跳到主要内容</a><div class="app-shell"><aside class="sidebar">'
        f'<a class="brand" href="/"><span class="brand-mark">{icon("box", 26)}</span><span><b>循分</b><small>SORTING WORKSPACE</small></span></a>'
        '<div class="nav-caption">工作空间</div><nav aria-label="主导航">' + nav + '</nav>'
        '<div class="sidebar-footer"><span class="sidebar-dot"></span><div><strong>智能机械臂垃圾分拣</strong><small>识别 · 抓取 · 分类投放</small></div></div></aside>'
        '<div class="main-shell"><header class="topbar"><div class="breadcrumb">工作台 <span>/</span> <b>' + title + '</b></div>'
        f'<span class="source-tag">{source_label}</span></header><main id="main-content"><div class="page-heading"><div><div class="eyebrow">SORTING WORKSPACE</div>'
        f'<h1>{title}</h1><p>{DESCRIPTIONS[path]}</p></div><div class="sync-area"><span id="connection-state" class="connection checking" role="status"><i></i>正在连接</span>'
        '<span id="last-updated" class="last-updated">尚未同步</span><button id="refresh-button" class="button refresh-button" type="button" aria-label="立即更新">' + icon("refresh", 17) + '更新</button></div></div>'
        '<div id="connection-error" class="error-banner" role="alert" hidden>数据更新失败，当前显示上次收到的记录。正在自动重试。</div>'
        '<div id="pending-banner" class="pending-banner" role="status" aria-live="polite" hidden></div>'
        '<noscript><div class="info-note">JavaScript 未启用，当前为首屏记录；请手动刷新获取新数据。</div></noscript>'
        + renderer(data) + '<footer class="page-footer"><span>循分 · 智能分拣工作台</span><span>统计基于收到的事件记录</span></footer></main></div></div>'
        f'<script type="application/json" id="initial-data">{bootstrap}</script></body></html>')


def serve(host="0.0.0.0", port=8765, store=None, data_source=None):
    if store is None:
        store = EventStore()
    server = ThreadingHTTPServer((host, port), make_handler(store, data_source))
    server.store = store
    return server
