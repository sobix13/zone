#!/usr/bin/env bash
# Compatibility entrypoint. V3 uses one independent recovery service and a lock.
set -euo pipefail
task_app_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
task_service="${MZ_SERVICE:-melee-zone.service}"
task_python="${MZ_PYTHON:-}"
if [[ -z "$task_python" ]]; then
    task_python="$(systemctl show "$task_service" -p ExecStart --value | sed -n 's/.*path=\([^ ;]*\).*/\1/p')"
fi
if [[ ! -x "$task_python" ]]; then
    printf '%s\n' 'Use install.sh to install the V3 recovery service, or set MZ_PYTHON.' >&2
    exit 1
fi
cd -- "$task_app_dir"
exec "$task_python" -u recovery_daemon.py
