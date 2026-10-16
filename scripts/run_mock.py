"""用假检测和假机械臂跑一遍主路径，并把事件交给看板。"""

import json
import urllib.request

from control.arm import MockArm
from control.sorter import SmileScript, Sorter
from control.voice import START, parse_command
from shared.schemas import DetectResult
from vision.detector import MockDetector, ScriptedColorTracker


def build_demo(clock):
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
        face=SmileScript([True, False]),
        clock=clock,
    )
    return sorter, arm


def post_event(event, url):
    data = json.dumps(event.to_dict()).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=2) as response:
        return response.status


def main():
    if parse_command(START) != "start":
        raise SystemExit("语音启动词未接通")
    tick = {"now": 1000}

    def clock():
        tick["now"] += 100
        return tick["now"]

    sorter, _arm = build_demo(clock)
    for _ in range(3):
        event = sorter.run_once()
        print(json.dumps(event.to_dict(), ensure_ascii=False))


if __name__ == "__main__":
    main()
