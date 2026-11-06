#!/usr/bin/env bash
# Read-only board preflight: never opens Arm_Device or sends servo/I2C commands.
set +e

PROJECT=/root/garbage-classification
PYTHON=/root/miniconda3/envs/ros-arm-env/bin/python
MODEL="$PROJECT/models/blocks4_v3/blocks4_yolov8n.om"

check_path() {
  if [ -e "$1" ]; then
    printf 'OK   %s\n' "$1"
  else
    printf 'MISS %s\n' "$1"
  fi
}

echo "== Required files =="
check_path /usr/local/Ascend/ascend-toolkit/set_env.sh
check_path /opt/ros/humble/setup.bash
check_path /root/ros2_robot_arm/ros2_ws/install/setup.bash
check_path /root/robot_arm_dependency/0.py_install/Arm_Lib/Arm_Lib.py
check_path /dev/i2c-7
check_path "$MODEL"

echo
echo "== Camera devices (no capture attempted) =="
shopt -s nullglob
video_nodes=(/dev/video*)
if [ ${#video_nodes[@]} -eq 0 ]; then
  echo "NO /dev/video* nodes"
else
  printf '%s\n' "${video_nodes[@]}"
fi
if command -v v4l2-ctl >/dev/null 2>&1; then
  v4l2-ctl --list-devices 2>&1
fi
if command -v lsusb >/dev/null 2>&1; then
  lsusb
fi

echo
echo "== Python imports =="
if [ -e /usr/local/Ascend/ascend-toolkit/set_env.sh ]; then
  source /usr/local/Ascend/ascend-toolkit/set_env.sh
fi
if [ -e /opt/ros/humble/setup.bash ]; then
  source /opt/ros/humble/setup.bash
fi
if [ -e /root/ros2_robot_arm/ros2_ws/install/setup.bash ]; then
  source /root/ros2_robot_arm/ros2_ws/install/setup.bash
fi
export PYTHONPATH="/root/robot_arm_dependency/0.py_install:${PYTHONPATH:-}"
if [ -x "$PYTHON" ]; then
  "$PYTHON" -c 'import cv2, numpy, ais_bench, Arm_Lib; print("cv2", cv2.__version__); print("numpy", numpy.__version__); print("ais_bench", ais_bench.__file__); print("Arm_Lib", Arm_Lib.__file__)'
else
  echo "MISS python environment: $PYTHON"
fi

echo
echo "== IK service discovery (read-only, 8 second timeout) =="
if command -v ros2 >/dev/null 2>&1; then
  service_output=$(ROS2CLI_DISABLE_DAEMON=1 timeout 8 ros2 service list 2>&1)
  if printf '%s\\n' "$service_output" | grep -Fq '/trial_service'; then
    printf '%s\\n' "$service_output" | grep -F '/trial_service'
  else
    echo "trial_service NOT FOUND (start the coursework IK server)"
    if [ -n "$service_output" ]; then
      printf '%s\\n' "$service_output" | head -10
    fi
  fi
else
  echo "ROS 2 CLI unavailable after sourcing"
fi
echo
echo "No arm device was opened and no motion command was sent."
