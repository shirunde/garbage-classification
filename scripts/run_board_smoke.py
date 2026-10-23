"""开发板真臂冒烟测试（本机没有 Arm_Lib，不要跑这个）。

用法（在板上仓库根目录）：
  python scripts/run_board_smoke.py safe     # 回安全位
  python scripts/run_board_smoke.py wave     # 挥手
  python scripts/run_board_smoke.py grasp recyclable  # 固定点抓一次并投到可回收点
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from control.arm import BoardArm, CommError
from shared.schemas import DetectResult


def main():
    parser = argparse.ArgumentParser(description="BoardArm 冒烟测试")
    parser.add_argument("action", choices=("safe", "wave", "grasp"))
    parser.add_argument(
        "cls",
        nargs="?",
        default="recyclable",
        choices=("recyclable", "hazardous", "kitchen", "other"),
    )
    args = parser.parse_args()

    try:
        arm = BoardArm()
    except ImportError as exc:
        print(exc)
        sys.exit(1)

    try:
        if args.action == "safe":
            arm.go_safe()
            print("已回安全位")
        elif args.action == "wave":
            arm.wave()
            print("挥手完成")
        else:
            detect = DetectResult(args.cls, 320, 240, 0.9, 1)
            ok = arm.grasp(detect)
            print("抓取投放成功" if ok else "抓取投放失败")
    except CommError as exc:
        print(f"通信/动作失败: {exc}")
        sys.exit(2)


if __name__ == "__main__":
    main()
