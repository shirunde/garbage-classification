"""Run the dashboard's fixed, single-cycle board command."""

import subprocess
import threading


class FixedSortJob:
    def __init__(self, ssh_host, verify_placement=False):
        board_command = (
            "cd /root/garbage-classification/position_trial && "
            "bash scripts/run_fixed_sort.sh --execute "
            "--model ../models/blocks4_v3/blocks4_yolov8n.om "
            "--dashboard-url http://127.0.0.1:18765"
        )
        if verify_placement:
            board_command += " --verify-placement --pan-to-bin --qwen-verify"
        self.command = [
            "ssh", "-T", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
            "-o", "ConnectTimeout=5", "-o", "ServerAliveInterval=5",
            "-o", "ServerAliveCountMax=3", ssh_host, board_command,
        ]
        self.lock = threading.Lock()
        self.state = {"status": "idle", "message": "就绪"}

    def snapshot(self):
        with self.lock:
            return dict(self.state)

    def start(self):
        with self.lock:
            if self.state["status"] == "running":
                return False
            self.state = {"status": "running", "message": "正在执行固定点分拣"}
            threading.Thread(target=self._run, daemon=True).start()
            return True

    def _run(self):
        try:
            result = subprocess.run(self.command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    encoding="utf-8", errors="replace", check=False)
            status = "completed" if result.returncode == 0 else "stopped"
            message = next((line for line in reversed(result.stdout.splitlines()) if line.startswith((
                "落点核验通过", "千问未在目标格", "动作完成", "本次未完成分拣", "已停止",
            ))), "分拣命令已结束")
            if message.startswith("千问未在目标格"):
                status = "stopped"
            if result.returncode == 73:
                message = "主板已有机械臂任务，未启动本次分拣"
            elif result.returncode == 255:
                message = "主板 SSH 连接中断，请先确认现场状态"
            elif result.returncode != 0 and message == "分拣命令已结束":
                message = f"分拣命令中止（退出码 {result.returncode}）"
        except OSError:
            status, message = "stopped", "无法调用本机 SSH"
        with self.lock:
            self.state = {"status": status, "message": message}
