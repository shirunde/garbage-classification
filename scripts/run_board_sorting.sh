#!/usr/bin/env bash
# Load the board's Ascend, ROS 2, and DOFBOT driver environments, then run the app.
set -euo pipefail

source /usr/local/Ascend/ascend-toolkit/set_env.sh
source /opt/ros/humble/setup.bash
source /root/ros2_robot_arm/ros2_ws/install/setup.bash
export PYTHONPATH="/root/robot_arm_dependency/0.py_install:${PYTHONPATH:-}"

exec /root/miniconda3/envs/ros-arm-env/bin/python \
  /root/garbage-classification/scripts/run_board_sorting.py "$@"
