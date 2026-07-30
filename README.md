# Drime Desktop for Linux (unofficial)

[Drime](https://drime.cloud) only ships its desktop app for Windows and macOS. This repo recreates the desktop experience on Linux using [rclone's native Drime backend](https://rclone.org/drime/) — an integration [officially announced by Drime](https://drime.cloud/blog-posts/drime-now-supports-native-rclone-integration) — plus a bit of desktop glue. No reverse engineering, no Wine: just supported APIs.

## What you get

| Component | What it is | Official-app equivalent |
|---|---|---|
| `~/Drime` | Virtual drive: your whole account mounted on demand with local caching (`rclone mount`, VFS full cache), auto-mounted at login, visible in your file manager's sidebar | The virtual "Drime drive" |
| `~/DrimeSync` | Two-way synced folder mirroring the `Sync` folder of your cloud every 15 minutes (`rclone bisync` + systemd timer) | Dropbox-style sync folder |
| "Drime" app icon | app.drime.cloud in its own window (Chromium `--app` mode) for sharing, previews, settings | The app's UI |
| `pydrime` (optional) | Third-party CLI for scripted uploads/downloads | — |

## Requirements

- Linux with a systemd user session and FUSE. Developed on **Fedora 44 / GNOME**; any distro works if the paths below exist, but the GNOME Files bookmark step assumes GTK.
- **rclone ≥ 1.73** (the Drime backend landed in 1.73). Fedora: `sudo dnf upgrade rclone`
- `fuse3` (Fedora preinstalls it)
- A Chromium-based browser for the web-app window (Flatpak Chromium/Brave, chromium, or Chrome — auto-detected; skipped if none)
- A Drime account and an **API token**: app.drime.cloud → **Settings → Developer → create token**

## Install

```bash
git clone https://github.com/DaveTheGameDev/drime-desktop-fedora.git
cd drime-desktop-fedora
./install.sh                 # add --with-pydrime for the CLI too
```

The script asks for your API token on first run (input is hidden and goes straight into `~/.config/rclone/rclone.conf` — it never touches shell history or this repo). It is idempotent: re-running skips whatever is already set up.

It also downloads the Drime logo and sets it as the custom icon of the `~/Drime` folder (GNOME Files shows it in the file view) and of the app launcher.

<details>
<summary>Manual install (what the script does)</summary>

1. `rclone config create drime drime access_token=<TOKEN>`
2. Copy `systemd/*.service` and `systemd/*.timer` to `~/.config/systemd/user/`
3. `systemctl --user daemon-reload && systemctl --user enable --now rclone-drime-mount.service`
4. Optional: `gio set ~/Drime metadata::custom-icon file://$HOME/.local/share/icons/drime.png` for the folder icon
5. `mkdir ~/DrimeSync && touch ~/DrimeSync/RCLONE_TEST && rclone copy ~/DrimeSync/RCLONE_TEST drime:Sync/`
6. `rclone bisync ~/DrimeSync drime:Sync --size-only --create-empty-src-dirs --check-access --resync`
7. `systemctl --user enable --now drime-bisync.timer`
8. Fill in `desktop/drime.desktop` (`@APP_CMD@`, `@ICON_PATH@`) and copy it to `~/.local/share/applications/`; the icon is at `https://app.drime.cloud/favicon/icon-512x512.png`
</details>

## Everyday use

- Work in `~/Drime` for anything in your account — saves upload automatically (files are cached locally up to 10 GB, so recently used files open instantly).
- Drop things in `~/DrimeSync` for an always-mirrored offline copy of the cloud's `Sync` folder.
- **Do not delete `~/DrimeSync/RCLONE_TEST`** — it's a safety marker; sync aborts rather than mass-deleting if either side ever looks wrong.

Handy commands:

```bash
systemctl --user status rclone-drime-mount   # mount health
systemctl --user start drime-bisync          # sync right now
journalctl --user -u drime-bisync -e         # sync logs
systemctl --user list-timers drime-bisync.timer
```

## Caveats

- **Drime's API stores no modification times or hashes**, so the sync folder detects changes by file size only. An edit that keeps a file's exact byte size won't be picked up by `~/DrimeSync`. This is rare, but for important work prefer `~/Drime` — the mount always uploads what you save.
- Tune cache size/behavior in `systemd/rclone-drime-mount.service` (`--vfs-cache-max-size`, `--dir-cache-time`); changes made in the cloud can take up to a minute to appear in `~/Drime`.
- Drime's own desktop apps are beta; the rclone backend is young too. Keep backups of anything irreplaceable.
- The GNOME Files **sidebar** bookmark keeps the generic folder glyph: Nautilus hardcodes bookmark icons (`folder-symbolic`), so only the folder in the main view and the app launcher show the Drime logo. (A colored sidebar icon is possible via an `/etc/fstab` entry with `x-gvfs-icon=`, but that needs root and a per-machine manual step, so this project deliberately stays user-level.)

## Uninstall

```bash
./uninstall.sh                  # removes mount, timer, launcher, caches
./uninstall.sh --purge-config   # ...and the rclone remote (API token) + pydrime config
```

What is removed: the systemd units, the mounted drive (unmounted, empty mount dir deleted), the app launcher and icon, the file-manager bookmark, rclone's local caches and bisync state.

What is **kept**: `~/DrimeSync` and everything in your cloud account — always; plus your API token/rclone remote and pydrime config unless you pass `--purge-config`.

## Repo layout

```
install.sh / uninstall.sh   # setup and removal scripts
systemd/                    # user units: mount service, bisync service + timer
desktop/drime.desktop       # launcher template (browser and icon filled at install)
```

---

*Unofficial project, not affiliated with Drime. Built on [rclone](https://rclone.org/drime/) and [pydrime](https://pydrime.readthedocs.io/).*
