"""用假检测和假机械臂跑一遍主路径，并把事件交给看板。"""

import json
import urllib.request

from control.arm import MockArm
from control.session import SortingSession
from control.sorter import SmileScript, Sorter
from control.voice import START
from dashboard.store import EventStore
from shared.schemas import DetectResult
from vision.detector import MockDetector, ScriptedColorTracker


def build_demo(clock, store):
    detector = MockDetector(
        [
            DetectResult("recyclable", 320, 240, 0.91, 1),
            DetectResult("kitchen", 300, 220, 0.62, 2),
            None,
        ]
    )
    arm = MockArm([True, True])
    sorter = Sorter(
        detector=detector,
        arm=arm,
        color_tracker=ScriptedColorTracker(),
        face=SmileScript([True, True, False]),
        clock=clock,
        sink=store,
    )
    return SortingSession(sorter, store)


def post_event(event, url):
    data = json.dumps(event.to_dict()).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=2) as response:
        return response.status


def main():
    tick = {"now": 1000}

    def clock():
        tick["now"] += 100
        return tick["now"]

    store = EventStore()
    session = build_demo(clock, store)
    session.handle_text(START)
    while session.mode == "running":
        event = session.tick()
        if event is not None:
            print(json.dumps(event.to_dict(), ensure_ascii=False))


if __name__ == "__main__":
    main()
