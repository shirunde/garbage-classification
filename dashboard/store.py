"""看板数据。页面和分拣会话都走这里，事件同时追加到日志。"""

import json

from shared.schemas import CLASS_LABELS, Reason, SortEvent


class EventStore:
    def __init__(self, log_path=None):
        self.events = []
        self.pending_cls = None
        self.log_path = log_path

    def show_pending(self, cls):
        self.pending_cls = cls

    def publish(self, event):
        return self.add(event)

    def add(self, event):
        if isinstance(event, SortEvent):
            payload = event.to_dict()
        else:
            payload = dict(event)
            SortEvent(**payload)
        self.events.append(payload)
        if self.log_path:
            with open(self.log_path, "a", encoding="utf-8") as log_file:
                log_file.write(json.dumps(payload, ensure_ascii=False) + "\n")
        return payload

    def summary(self):
        total = len(self.events)
        success = sum(1 for event in self.events if event["ok"])
        return {
            "total": total,
            "success": success,
            "failed": total - success,
        }

    def by_class(self):
        counts = {name: 0 for name in CLASS_LABELS}
        for event in self.events:
            if event["cls"] in counts:
                counts[event["cls"]] += 1
        return counts

    def fallback_counts(self):
        counts = {reason: 0 for reason in Reason.ALL if reason != Reason.OK}
        for event in self.events:
            if event["reason"] in counts:
                counts[event["reason"]] += 1
        return counts
