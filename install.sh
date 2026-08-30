#!/usr/bin/env bash
# Installs the unofficial Drime desktop setup from a git checkout.
# Prefer the RPM/DEB from the GitHub Releases page — this script is the
# terminal/advanced path. Idempotent: safe to re-run.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

if command -v drime-desktop >/dev/null; then
    exec drime-desktop --install "$@"        # the package is installed: use it
fi

if command -v rpm >/dev/null; then       # Fedora/RPM distros: check the packages
    missing=()
    for p in python3-gobject gtk4 libadwaita webkitgtk6.0 rclone fuse3; do
        rpm -q "$p" >/dev/null 2>&1 || missing+=("$p")
    done
    if [ ${#missing[@]} -gt 0 ]; then
        echo "Missing packages. Install them first:  sudo dnf install ${missing[*]}" >&2
        exit 1
    fi
elif command -v dpkg-query >/dev/null; then   # Ubuntu/Debian. rclone is left to the wizard: the
    missing=()                                # distribution's is too old, it must come from rclone.org
    for p in python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 gir1.2-webkit-6.0 fuse3; do
        dpkg-query -W -f='${Status}' "$p" 2>/dev/null | grep -q "install ok installed" || missing+=("$p")
    done
    if [ ${#missing[@]} -gt 0 ]; then
        echo "Missing packages. Install them first:  sudo apt install ${missing[*]}" >&2
        exit 1
    fi
fi
exec env PYTHONPATH="$PWD/src" DRIME_DESKTOP_SRC="$PWD" python3 -m drime_desktop.cli --install "$@"
