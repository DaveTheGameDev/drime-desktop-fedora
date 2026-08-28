#!/usr/bin/env bash
# Removes the unofficial Drime desktop setup (keeps ~/DrimeSync and your cloud data).
# Pass --purge-config to also delete the API token (rclone remote) and pydrime config.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

if command -v drime-desktop >/dev/null; then
    exec drime-desktop --uninstall "$@"
fi
exec env PYTHONPATH="$PWD/src" DRIME_DESKTOP_SRC="$PWD" python3 -m drime_desktop.cli --uninstall "$@"
