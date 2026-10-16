"""看板内存数据。写入后可立刻被四个页面读到。"""

from shared.schemas import CLASS_LABELS, Reason, SortEvent


class EventStore:
    def __init__(self):
        self.events = []

    def add(self, event):
        if isinstance(event, SortEvent):
            payload = event.to_dict()
        else:
            payload = dict(event)
            SortEvent(**payload)
        self.events.append(payload)
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
