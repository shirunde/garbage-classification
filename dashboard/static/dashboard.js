(() => {
  "use strict";
  const bootstrap = JSON.parse(document.getElementById("initial-data").textContent);
  const { config } = bootstrap;
  const classes = Object.keys(config.classes);
  const $ = (id) => document.getElementById(id);
  const escape = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  })[c]);
  let data = bootstrap.data;
  let page = 1;
  let busy = false;
  let timer;
  let lastSuccess = null;
  const filterIds = ["class-filter", "result-filter", "reason-filter", "event-search", "page-size"];

  function formatTime(value) {
    const number = Number(value);
    if (!Number.isFinite(number)) return String(value ?? "—");
    // 演示使用 1000、1200 等时标，不能将它们误显示为 1970 年的日期。
    if (number < 946684800) return "时标 " + number;
    const date = new Date(number < 100000000000 ? number * 1000 : number);
    return Number.isNaN(date.valueOf()) ? String(value) : date.toLocaleString("zh-CN", {
      month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false
    });
  }

  function eventRow(event) {
    const index = classes.indexOf(event.cls);
    const label = config.classes[event.cls] || event.cls || "无目标";
    const badge = event.ok ? "success" : event.reason === "timeout_no_target" ? "neutral" : "failure";
    const result = event.ok ? "成功" : badge === "neutral" ? "无目标" : "未成功";
    return '<tr><td class="event-id">#' + escape(event.event_id) + '</td><td class="time-cell">' + escape(formatTime(event.ts)) +
      '</td><td><span class="class-label"><i class="class-dot class-' + (index < 0 ? 4 : index) + '"></i>' + escape(label) +
      '</span></td><td>' + (event.bin_id ? escape(event.bin_id) + " 号箱" : "—") + '</td><td><span class="badge ' + badge + '">' +
      result + '</span></td><td class="numeric">' + escape(event.cost_ms) + '<span class="unit"> ms</span></td><td class="reason-cell">' +
      escape(config.reasons[event.reason] || event.reason) + '</td></tr>';
  }

  function filteredEvents() {
    let events = data.events.slice().reverse();
    if (!$('filters')) return events;
    const cls = $('class-filter').value;
    const result = $('result-filter').value;
    const reason = $('reason-filter').value;
    const query = $('event-search').value.trim().toLocaleLowerCase();
    return events.filter((event) => {
      if (cls && (cls === "__none" ? !!event.cls : event.cls !== cls)) return false;
      if (result === "success" && !event.ok) return false;
      if (result === "failed" && event.ok) return false;
      if (reason && event.reason !== reason) return false;
      const text = [event.event_id, event.cls, config.classes[event.cls], event.reason, config.reasons[event.reason]].join(" ").toLocaleLowerCase();
      return !query || text.includes(query);
    });
  }

  function renderEvents() {
    if (!$('event-rows')) return;
    const events = filteredEvents();
    const pageSize = $('page-size') ? Number($('page-size').value) : 5;
    const pages = Math.max(1, Math.ceil(events.length / pageSize));
    page = Math.min(page, pages);
    const current = events.slice((page - 1) * pageSize, page * pageSize);
    $('event-rows').innerHTML = current.length ? current.map(eventRow).join("") :
      '<tr><td colspan="7"><div class="empty-state"><strong>' +
      (data.events.length ? "没有符合条件的事件" : "暂无事件") + '</strong><span>' +
      (data.events.length ? "尝试调整筛选条件，或点击重置。" : "收到分拣记录后，会显示在这里。") + '</span></div></td></tr>';
    if ($('result-count')) {
      const from = events.length ? (page - 1) * pageSize + 1 : 0;
      const to = Math.min(page * pageSize, events.length);
      $('result-count').textContent = "共 " + events.length + " 条匹配 · 显示 " + from + "–" + to + " 条";
      $('page-label').textContent = page + " / " + pages;
      $('previous-page').disabled = page <= 1;
      $('next-page').disabled = page >= pages;
    }
  }

  function renderCategories() {
    if ($('category-bars')) {
      const total = Object.values(data.by_class).reduce((sum, count) => sum + count, 0);
      $('category-bars').innerHTML = classes.map((name, index) => {
        const count = data.by_class[name] || 0;
        const share = total ? (count / total * 100).toFixed(1) : "0.0";
        return '<div class="category-row"><div class="category-line"><span class="class-label"><i class="class-dot class-' + index + '"></i>' +
          escape(config.classes[name]) + '</span><span><b>' + count + '</b><small> 条 · ' + share + '%</small></span></div><div class="bar-track">' +
          '<span class="class-bg-' + index + '" style="width:' + share + '%"></span></div></div>';
      }).join("");
    }
    document.querySelectorAll('[data-class-count]').forEach((node) => {
      node.textContent = data.by_class[node.dataset.classCount] || 0;
    });
    document.querySelectorAll('[data-class-success]').forEach((node) => {
      node.textContent = data.events.filter((event) => event.cls === node.dataset.classSuccess && event.ok).length;
    });
  }

  function renderPending() {
    const pending = data.pending_cls;
    const label = config.classes[pending] || pending;
    const banner = $('pending-banner');
    banner.hidden = !pending;
    banner.textContent = pending ? "待确认目标：" + label + "。等待表情确认，超时后将跳过。" : "";
    const node = $('pending-content');
    if (node) {
      const symbol = pending ? '<path d="M12 7v6m0 4h.01"/><path d="M10 3 2 20h20L14 3Z"/>' : '<path d="m5 12 4 4L19 6"/>';
      node.innerHTML = '<div class="pending-visual' + (pending ? " waiting" : "") + '"><svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + symbol +
        '</svg></div><p class="eyebrow">' + (pending ? "等待表情确认" : "待确认类别") + '</p><h3>' +
        (pending ? escape(label) : "当前无待确认目标") + '</h3><p class="muted">' +
        (pending ? "请在规定时间内确认当前目标，超时后将跳过。" : "需要确认时，目标类别会显示在这里。") + '</p>';
    }
  }

  function render(next) {
    data = next;
    const values = { ...data.summary, rate: data.summary.total ? Math.round(100 * data.summary.success / data.summary.total) + "%" : "—" };
    document.querySelectorAll('[data-metric]').forEach((node) => { node.textContent = values[node.dataset.metric]; });
    renderEvents();
    renderCategories();
    renderPending();
    document.querySelectorAll('[data-reason-count]').forEach((node) => { node.textContent = data.fallback[node.dataset.reasonCount] || 0; });
    if ($('latest-alert')) {
      const last = data.events[data.events.length - 1];
      $('latest-alert').textContent = last && last.reason === "comm_error" ?
        "最近一条事件报告通信异常，请检查设备连接；恢复运动需由控制端确认。" :
        "异常计数是历史累计值，当前状态请以设备实际情况为准。";
    }
  }

  function setConnection(ok) {
    const state = $('connection-state');
    state.className = "connection " + (ok ? "connected" : "disconnected");
    state.innerHTML = '<i></i>' + (ok ? "数据同步正常" : "数据更新失败");
    $('connection-error').hidden = ok;
    if ($('device-api-state')) $('device-api-state').textContent = ok ? "连接正常" : "更新失败";
  }

  function updateTimestamp() {
    if (!lastSuccess) return;
    const age = Math.floor((Date.now() - lastSuccess) / 1000);
    $('last-updated').textContent = "最后同步 " + new Date(lastSuccess).toLocaleTimeString("zh-CN", { hour12: false }) +
      (age > 5 ? " · " + age + " 秒前" : "");
  }

  async function refresh() {
    if (busy) return;
    clearTimeout(timer);
    busy = true;
    $('refresh-button').disabled = true;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 5000);
    try {
      const response = await fetch("/api/events", { cache: "no-store", signal: controller.signal });
      if (!response.ok) throw new Error("HTTP " + response.status);
      const next = await response.json();
      if (!Array.isArray(next.events) || !next.summary || !next.by_class || !next.fallback) throw new Error("Invalid response");
      render(next);
      lastSuccess = Date.now();
      updateTimestamp();
      setConnection(true);
    } catch (_) {
      setConnection(false);
    } finally {
      clearTimeout(timeout);
      busy = false;
      $('refresh-button').disabled = false;
      timer = setTimeout(refresh, 500);
    }
  }

  function saveFilters() {
    try {
      const values = Object.fromEntries(filterIds.map((id) => [id, $(id).value]));
      sessionStorage.setItem("sorting-filters-v1", JSON.stringify(values));
    } catch (_) { /* 禁用存储时筛选仍可在当前页面工作。 */ }
  }

  if ($('filters')) {
    try {
      const values = JSON.parse(sessionStorage.getItem("sorting-filters-v1") || "{}");
      filterIds.forEach((id) => {
        const node = $(id);
        if (typeof values[id] !== "string") return;
        if (node.tagName === "SELECT" && !Array.from(node.options).some((option) => option.value === values[id])) return;
        node.value = values[id];
      });
    } catch (_) { /* 保留默认筛选值。 */ }
    $('filters').addEventListener("submit", (event) => event.preventDefault());
    filterIds.forEach((id) => $(id).addEventListener(id === "event-search" ? "input" : "change", () => {
      page = 1; saveFilters(); renderEvents();
    }));
    $('filters').addEventListener("reset", (event) => {
      event.preventDefault();
      filterIds.forEach((id) => { $(id).value = id === "page-size" ? "10" : ""; });
      page = 1; saveFilters(); renderEvents();
    });
    $('previous-page').addEventListener("click", () => { page -= 1; renderEvents(); });
    $('next-page').addEventListener("click", () => { page += 1; renderEvents(); });
  }
  $('refresh-button').addEventListener("click", refresh);
  window.addEventListener("pagehide", () => clearTimeout(timer));
  render(data);
  refresh();
  setInterval(updateTimestamp, 1000);
})();
