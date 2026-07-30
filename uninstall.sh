#!/usr/bin/env bash
# Removes the unofficial Drime desktop setup.
# By default your data is kept: ~/DrimeSync, everything in the cloud, and the
# rclone/pydrime configuration (API token) stay untouched.
set -uo pipefail

UNIT_DIR="$HOME/.config/systemd/user"
MOUNT_POINT="$HOME/Drime"
REMOTE="drime"
PURGE_CONFIG=0

for arg in "$@"; do
    case "$arg" in
        --purge-config) PURGE_CONFIG=1 ;;
        -h|--help)
            echo "Usage: $0 [--purge-config]"
            echo "  --purge-config   also delete the rclone remote (API token) and pydrime config"
            exit 0 ;;
        *) echo "Unknown option: $arg" >&2; exit 1 ;;
    esac
done

info() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }

# Stop and remove units
systemctl --user disable --now drime-bisync.timer 2>/dev/null
systemctl --user stop drime-bisync.service 2>/dev/null
systemctl --user disable --now rclone-drime-mount.service 2>/dev/null
fusermount3 -u "$MOUNT_POINT" 2>/dev/null
rm -f "$UNIT_DIR/rclone-drime-mount.service" \
      "$UNIT_DIR/drime-bisync.service" \
      "$UNIT_DIR/drime-bisync.timer"
systemctl --user daemon-reload
systemctl --user reset-failed 2>/dev/null
info "systemd units removed, drive unmounted"

# Remove launcher, icon, bookmark
rm -f "$HOME/.local/share/applications/drime.desktop" "$HOME/.local/share/icons/drime.png"
update-desktop-database "$HOME/.local/share/applications" 2>/dev/null
[ -f "$HOME/.config/gtk-3.0/bookmarks" ] && sed -i "\|^file://$MOUNT_POINT |d" "$HOME/.config/gtk-3.0/bookmarks"
info "launcher, icon and file-manager bookmark removed"

# Remove caches and bisync state (not data)
rm -rf "$HOME/.cache/rclone/vfs/$REMOTE" "$HOME/.cache/rclone/vfsMeta/$REMOTE"
find "$HOME/.cache/rclone/bisync" -name '*DrimeSync*' -delete 2>/dev/null
rmdir "$MOUNT_POINT" 2>/dev/null
info "rclone caches and bisync state removed"

if [ "$PURGE_CONFIG" = 1 ]; then
    rclone config delete "$REMOTE" 2>/dev/null
    rm -rf "$HOME/.config/pydrime"
    python3 -m pip uninstall -y -q pydrime 2>/dev/null
    info "rclone remote, pydrime and their credentials removed"
fi

echo
info "Uninstalled. Kept on purpose:"
echo "  - ~/DrimeSync and all files in your Drime cloud account"
if [ "$PURGE_CONFIG" = 0 ]; then
    echo "  - rclone remote '${REMOTE}:' and pydrime config (rerun with --purge-config to remove)"
fi
