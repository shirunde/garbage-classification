"""ROS 2 CLI client for the DOFBOT coursework inverse-kinematics service."""

from __future__ import annotations

import re
import shutil
import subprocess

class RosKinematicsClient:
    def __init__(self, service_name="/trial_service", timeout_sec=10.0):
        self.ros2 = shutil.which("ros2")
        if self.ros2 is None:
            raise RuntimeError("ros2 CLI not found; source the board ROS 2 environment first")
        self.service_name = service_name
        self.timeout_sec = float(timeout_sec)

    def solve(self, x_m, y_m, z_m):
        if float(z_m) < 0.2:
            raise ValueError(
                "The board IK server treats tar_z below 0.2 m as a special-height mode; "
                "calibrate a direct target height at or above 0.2 m before sorting"
            )
        payload = (
            "{kin_name: ik, "
            f"tar_x: {float(x_m):.8f}, tar_y: {float(y_m):.8f}, "
            f"tar_z: {float(z_m):.8f}"
            "}"
        )
        try:
            completed = subprocess.run(
                [
                    self.ros2, "service", "call", self.service_name,
                    "dofbot_info/srv/Kinemarics", payload,
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=self.timeout_sec,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("DOFBOT IK service timed out") from exc
        if completed.returncode != 0:
            raise RuntimeError(
                "DOFBOT IK service failed: " + (completed.stderr or completed.stdout).strip()
            )
        response = completed.stdout
        joints = []
        for index in range(1, 6):
            match = re.search(rf"joint{index}\s*[=:]\s*([-+0-9.eE]+)", response)
            if match is None:
                raise RuntimeError(f"DOFBOT IK response has no joint{index}: {response.strip()}")
            joints.append(float(match.group(1)))
        if not all(0.0 <= angle <= 270.0 for angle in joints):
            raise RuntimeError(f"DOFBOT IK returned out-of-range joints: {joints}")
        return joints

    def close(self):
        return None
