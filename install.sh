#!/usr/bin/env bash
set -Eeuo pipefail
release_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec "${MZ_INSTALL_PYTHON:-python3}" "$release_root/scripts/install_release.py" "$@"
