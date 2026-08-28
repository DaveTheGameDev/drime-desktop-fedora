#!/usr/bin/env bash
# Installs the unofficial Drime desktop setup from a git checkout.
# Prefer the RPM from the GitHub Releases page — this script is the
# terminal/advanced path. Idempotent: safe to re-run.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

if command -v drime-desktop >/dev/null; then
    exec drime-desktop --install "$@"        # RPM is installed: use it
fi

missing=()
for p in python3-gobject gtk4 libadwaita rclone fuse3; do
    rpm -q "$p" >/dev/null 2>&1 || missing+=("$p")
done
if [ ${#missing[@]} -gt 0 ]; then
    echo "Missing packages. Install them first:  sudo dnf install ${missing[*]}" >&2
    exit 1
fi
exec env PYTHONPATH="$PWD/src" DRIME_DESKTOP_SRC="$PWD" python3 -m drime_desktop.cli --install "$@"
