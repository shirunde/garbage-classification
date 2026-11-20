#!/usr/bin/env bash
set -eo pipefail
project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
source /usr/local/Ascend/ascend-toolkit/set_env.sh
source /opt/ros/humble/setup.bash
source /root/ros2_robot_arm/ros2_ws/install/setup.bash
export PYTHONPATH="/root/robot_arm_dependency/0.py_install:${PYTHONPATH:-}"
for arg in "$@"; do
  if [[ "$arg" == "--execute" || "$arg" == "--approach-only" ]]; then
    exec flock -n -E 73 /run/lock/garbage-sort.lock /root/miniconda3/envs/ros-arm-env/bin/python "$project_dir/scripts/run_position_sort.py" "$@"
  fi
done
exec /root/miniconda3/envs/ros-arm-env/bin/python "$project_dir/scripts/run_position_sort.py" "$@"
