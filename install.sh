#!/usr/bin/env bash
# Installs the unofficial Drime desktop setup for Linux.
# Idempotent: safe to re-run; already-configured parts are skipped.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UNIT_DIR="$HOME/.config/systemd/user"
MOUNT_POINT="$HOME/Drime"
SYNC_DIR="$HOME/DrimeSync"
REMOTE="drime"
MIN_RCLONE="1.73.0"
WITH_PYDRIME=0

for arg in "$@"; do
    case "$arg" in
        --with-pydrime) WITH_PYDRIME=1 ;;
        -h|--help)
            echo "Usage: $0 [--with-pydrime]"
            echo "  --with-pydrime   also install the pydrime CLI (pip --user)"
            exit 0 ;;
        *) echo "Unknown option: $arg" >&2; exit 1 ;;
    esac
done

info() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33mWARNING:\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }

# --- Preflight ---------------------------------------------------------------
command -v rclone >/dev/null || die "rclone is not installed. On Fedora: sudo dnf install rclone"
command -v fusermount3 >/dev/null || die "fuse3 is not installed. On Fedora: sudo dnf install fuse3"
systemctl --user is-system-running >/dev/null 2>&1 || die "No systemd user session available."

rclone_version="$(rclone version | head -1 | sed 's/^rclone v//')"
if [ "$(printf '%s\n%s\n' "$MIN_RCLONE" "$rclone_version" | sort -V | head -1)" != "$MIN_RCLONE" ]; then
    die "rclone $rclone_version is too old — the Drime backend needs >= $MIN_RCLONE. On Fedora: sudo dnf upgrade rclone"
fi
info "rclone $rclone_version OK"

# --- Drime remote ------------------------------------------------------------
if rclone listremotes | grep -qx "${REMOTE}:"; then
    info "rclone remote '${REMOTE}:' already configured"
else
    echo "A Drime API token is required."
    echo "Get one at: app.drime.cloud -> Settings -> Developer -> create token"
    read -rsp "Paste your Drime API token: " token; echo
    [ -n "$token" ] || die "No token provided."
    rclone config create "$REMOTE" drime access_token="$token" >/dev/null
    info "Remote '${REMOTE}:' created"
fi
rclone about "${REMOTE}:" >/dev/null || die "Cannot reach Drime with the configured token."
info "Drime account reachable"

# --- Virtual drive mount -----------------------------------------------------
mkdir -p "$UNIT_DIR"
cp "$REPO_DIR/systemd/rclone-drime-mount.service" "$UNIT_DIR/"
systemctl --user daemon-reload
systemctl --user enable --now rclone-drime-mount.service
info "Virtual drive mounted at $MOUNT_POINT (auto-mounts at login)"

bookmarks="$HOME/.config/gtk-3.0/bookmarks"
mkdir -p "$(dirname "$bookmarks")" && touch "$bookmarks"
grep -q "file://$MOUNT_POINT " "$bookmarks" || printf 'file://%s Drime\n' "$MOUNT_POINT" >> "$bookmarks"

# --- Drime folder icon -------------------------------------------------------
icon_path="$HOME/.local/share/icons/drime.png"
mkdir -p "$(dirname "$icon_path")"
if [ ! -f "$icon_path" ]; then
    for size in 512x512 192x192 144x144; do
        curl -sf --max-time 20 "https://app.drime.cloud/favicon/icon-$size.png" -o "$icon_path" && break || true
    done
fi
if [ -f "$icon_path" ]; then
    gio set "$MOUNT_POINT" metadata::custom-icon "file://$icon_path" 2>/dev/null \
        && info "Drime icon applied to the $MOUNT_POINT folder" \
        || warn "Could not set a custom folder icon (gio metadata not supported here)."
fi

# --- Web app launcher --------------------------------------------------------
APP_CMD=""
if command -v flatpak >/dev/null && flatpak info org.chromium.Chromium >/dev/null 2>&1; then
    APP_CMD="flatpak run org.chromium.Chromium"
elif command -v flatpak >/dev/null && flatpak info com.brave.Browser >/dev/null 2>&1; then
    APP_CMD="flatpak run com.brave.Browser"
elif command -v chromium >/dev/null; then
    APP_CMD="chromium"
elif command -v chromium-browser >/dev/null; then
    APP_CMD="chromium-browser"
elif command -v google-chrome >/dev/null; then
    APP_CMD="google-chrome"
fi

if [ -n "$APP_CMD" ]; then
    mkdir -p "$HOME/.local/share/applications"
    [ -f "$icon_path" ] || warn "Could not download the Drime icon; launcher will have a generic icon."
    sed -e "s|@APP_CMD@|$APP_CMD|" -e "s|@ICON_PATH@|$icon_path|" \
        "$REPO_DIR/desktop/drime.desktop" > "$HOME/.local/share/applications/drime.desktop"
    update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
    info "Web app launcher installed (opens app.drime.cloud via: $APP_CMD)"
else
    warn "No Chromium-based browser found — skipping the web app launcher."
fi

# --- Two-way sync folder -----------------------------------------------------
mkdir -p "$SYNC_DIR"
touch "$SYNC_DIR/RCLONE_TEST"
if compgen -G "$HOME/.cache/rclone/bisync/*DrimeSync*" >/dev/null; then
    info "bisync already initialized — skipping --resync"
else
    rclone copy "$SYNC_DIR/RCLONE_TEST" "${REMOTE}:Sync/"
    rclone bisync "$SYNC_DIR" "${REMOTE}:Sync" --size-only --create-empty-src-dirs --check-access --resync
    info "bisync baseline established ($SYNC_DIR <-> ${REMOTE}:Sync)"
fi
cp "$REPO_DIR/systemd/drime-bisync.service" "$REPO_DIR/systemd/drime-bisync.timer" "$UNIT_DIR/"
systemctl --user daemon-reload
systemctl --user enable --now drime-bisync.timer
info "Sync timer enabled (every 15 min)"

# --- Optional: pydrime CLI ---------------------------------------------------
if [ "$WITH_PYDRIME" = 1 ]; then
    python3 -m pip install --user --quiet pydrime
    info "pydrime installed — run 'pydrime init' and paste the same API token"
fi

echo
info "Done. Summary:"
echo "  - Virtual drive:  $MOUNT_POINT (systemd unit: rclone-drime-mount.service)"
echo "  - Sync folder:    $SYNC_DIR <-> ${REMOTE}:Sync every 15 min (drime-bisync.timer)"
echo "  - Web app:        'Drime' in your application grid"
echo "  - Keep the RCLONE_TEST file in $SYNC_DIR — it is a safety marker."
