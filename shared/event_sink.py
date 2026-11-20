"""Durable producer journal and retry queue for the dashboard event API."""

import json
import sys
import uuid
from pathlib import Path
from urllib.request import Request, urlopen


class EventSink:
    def __init__(self, directory, dashboard_url=None, timeout=0.5):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.journal = self.directory / 'events.jsonl'
        self.queue = self.directory / 'event_outbox.jsonl'
        self.url = dashboard_url.rstrip('/') + '/api/events' if dashboard_url else None
        self.timeout = timeout

    def publish(self, event):
        payload = event.to_dict()
        # Queue first: even interruption between the two writes retains delivery.
        for path in (self.queue, self.journal):
            with path.open('a', encoding='utf-8') as file:
                file.write(json.dumps(payload, ensure_ascii=False) + '\n')
        self.flush()
        return payload

    def flush(self, limit=20):
        if not self.url or not self.queue.exists():
            return 0
        pending = [json.loads(line) for line in self.queue.read_text(encoding='utf-8').splitlines() if line.strip()]
        count = 0
        for payload in pending[:limit]:
            request = Request(self.url, data=json.dumps(payload).encode('utf-8'),
                              headers={'Content-Type': 'application/json'}, method='POST')
            try:
                with urlopen(request, timeout=self.timeout) as response:
                    if response.status not in (200, 201):
                        raise RuntimeError(f'HTTP {response.status}')
            except Exception as exc:
                print(f'事件保存在本地，等待补发: {exc}', file=sys.stderr)
                break
            count += 1
        if count:
            temporary = self.queue.with_name(self.queue.name + '.' + uuid.uuid4().hex + '.tmp')
            temporary.write_text(''.join(json.dumps(item, ensure_ascii=False) + '\n' for item in pending[count:]), encoding='utf-8')
            temporary.replace(self.queue)
        return count
