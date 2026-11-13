#!/usr/bin/env bash
# Fixed-point recognition and motion require Ascend and Arm_Lib, not ROS IK.
set -eo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
source /usr/local/Ascend/ascend-toolkit/set_env.sh
export PYTHONPATH="/root/robot_arm_dependency/0.py_install:${ROOT}:${PYTHONPATH:-}"
set -u
exec /root/miniconda3/envs/ros-arm-env/bin/python "${ROOT}/scripts/run_fixed_sort.py" "$@"
