"""看板数据。页面和分拣会话都走这里，事件同时追加到日志。"""

import json
import threading

from shared.schemas import CLASS_LABELS, Reason, SortEvent


class EventStore:
    def __init__(self, log_path=None):
        self.events = []
        self.pending_cls = None
        self.log_path = log_path
        self._lock = threading.RLock()
        self._by_id = {}

    def show_pending(self, cls):
        with self._lock:
            self.pending_cls = cls

    def publish(self, event):
        return self.add(event)

    def add(self, event):
        return self._accept(event, persist=True)

    def restore(self, event):
        return self._accept(event, persist=False)

    def _accept(self, event, persist):
        if isinstance(event, SortEvent):
            payload = event.to_dict()
        else:
            payload = dict(event)
            SortEvent(**payload)
        with self._lock:
            previous = self._by_id.get(payload['event_id'])
            if previous is not None:
                if previous != payload:
                    raise ValueError('event_id 已存在且内容不同')
                return dict(previous)
            if persist and self.log_path:
                with open(self.log_path, "a", encoding="utf-8") as log_file:
                    log_file.write(json.dumps(payload, ensure_ascii=False) + "\n")
            self.events.append(payload)
            self._by_id[payload['event_id']] = dict(payload)
        return payload

    def snapshot(self):
        """页面与轮询接口使用同一时刻的事件和统计。"""
        with self._lock:
            events = [dict(event) for event in self.events]
            success = sum(1 for event in events if event["ok"])
            unverified = sum(event['reason'] == Reason.COMMAND_COMPLETE for event in events)
            by_class = {name: 0 for name in CLASS_LABELS}
            fallback = {reason: 0 for reason in Reason.ALL if reason not in (Reason.OK, Reason.COMMAND_COMPLETE)}
            for event in events:
                if event["cls"] in by_class:
                    by_class[event["cls"]] += 1
                if event["reason"] in fallback:
                    fallback[event["reason"]] += 1
            return {
                "events": events,
                "summary": {"total": len(events), "success": success,
                            "failed": len(events) - success - unverified,
                            "unverified": unverified},
                "pending_cls": self.pending_cls,
                "by_class": by_class,
                "fallback": fallback,
            }

    def summary(self):
        return self.snapshot()['summary']

    def by_class(self):
        counts = {name: 0 for name in CLASS_LABELS}
        for event in self.events:
            if event["cls"] in counts:
                counts[event["cls"]] += 1
        return counts

    def fallback_counts(self):
        return self.snapshot()['fallback']
