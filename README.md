# Drime Desktop for Linux (unofficial)

[Drime](https://drime.cloud) only ships its desktop app for Windows and macOS. This project recreates the desktop experience on Fedora Linux using [rclone's native Drime backend](https://rclone.org/drime/) — an integration [officially announced by Drime](https://drime.cloud/blog-posts/drime-now-supports-native-rclone-integration) — plus a small GNOME app that sets everything up and keeps it running. No reverse engineering, no Wine: just supported APIs.

## What you get

| Component | What it is | Official-app equivalent |
|---|---|---|
| `~/Drime` | Virtual drive: your whole account mounted on demand with local caching (`rclone mount`, VFS full cache), auto-mounted at login, visible in your file manager's sidebar | The virtual "Drime drive" |
| `~/DrimeSync` | Two-way synced folder mirroring the `Sync` folder of your cloud every 15 minutes (`rclone bisync` + systemd timer) | Dropbox-style sync folder |
| **Drime** app | Setup wizard, status (drive, last/next sync), sync now, check for updates, update the browser, remove the setup | The app's settings / tray menu |
| **Drime Web** app | app.drime.cloud in its own window (Chromium `--app` mode) for sharing, previews, settings | The app's UI |
| `pydrime` (optional) | Third-party CLI for scripted uploads/downloads | — |

## Requirements

- **Fedora Workstation** (developed on Fedora 44 / GNOME). Other systemd + GTK4 distributions can use the [git checkout](#advanced-install-from-a-git-checkout) path.
- A Drime account and an **API token**: app.drime.cloud → **Settings → Developer → create token**
- Everything else (`rclone ≥ 1.73`, `fuse3`, GTK4/libadwaita) is pulled in by the package.
- For the web-app window: a Chromium-based browser. If none is installed the setup offers to install Chromium from Flathub.

## Install

1. Download the latest `drime-desktop-<version>.noarch.rpm` from the [Releases page](https://github.com/DaveTheGameDev/drime-desktop-fedora/releases).
2. Double-click it — GNOME Software opens and installs it (or run `sudo dnf install ./drime-desktop-*.rpm`).
3. Open **Drime** from your applications. The wizard asks for your API token and turns on the drive and the sync folder. That's it.

The token goes straight into `~/.config/rclone/rclone.conf` and nowhere else.

## Updating

- **Drime Desktop itself**: open **Drime → Updates → Check for updates**. If a newer release exists, *Download and install* fetches the RPM and opens it in GNOME Software, where you confirm the update. (Or download the new RPM from Releases and double-click it — same thing.)
- **The browser that hosts the web app** (Chromium/Brave Flatpak): **Drime → Updates → Update**, or *Open in Software*. GNOME Software also updates Flatpaks automatically with the rest of your system.
- **rclone** updates with your normal system updates.

Updates replace the systemd units under `/usr/lib/systemd/user/`; the running mount is not interrupted, new unit settings apply at the next login (or `systemctl --user daemon-reload && systemctl --user restart rclone-drime-mount`).

## Everyday use

- Work in `~/Drime` for anything in your account — saves upload automatically (files are cached locally up to 10 GB, so recently used files open instantly).
- Drop things in `~/DrimeSync` for an always-mirrored offline copy of the cloud's `Sync` folder.
- **Do not delete `~/DrimeSync/RCLONE_TEST`** — it's a safety marker; sync aborts rather than mass-deleting if either side ever looks wrong.
- The **Drime** app shows whether the drive is mounted and when the last sync ran; *Sync now* runs it immediately; the *Sync log* row shows the journal.

Terminal equivalents:

```bash
drime-desktop --status                       # same info as the app
systemctl --user status rclone-drime-mount   # mount health
systemctl --user start drime-bisync          # sync right now
journalctl --user -u drime-bisync -e         # sync logs
drime-desktop --help                         # --install, --uninstall, --open-web, --check-update
```

## Uninstall

1. **Drime → Remove → Remove my setup…** (or `drime-desktop --uninstall`, add `--purge-config` to also delete the API token). This unmounts the drive, disables the timer and removes the bookmark, caches and sync state.
2. Uninstall the *Drime* package in GNOME Software, or `sudo dnf remove drime-desktop`.

What is **kept**: `~/DrimeSync` and everything in your cloud account — always; plus your API token (rclone remote) and pydrime config unless you chose to delete them.

## Caveats

- **Drime's API stores no modification times or hashes**, so the sync folder detects changes by file size only. An edit that keeps a file's exact byte size won't be picked up by `~/DrimeSync`. This is rare, but for important work prefer `~/Drime` — the mount always uploads what you save.
- Tune cache size/behavior in `systemd/rclone-drime-mount.service` (`--vfs-cache-max-size`, `--dir-cache-time`); changes made in the cloud can take up to a minute to appear in `~/Drime`.
- Drime's own desktop apps are beta; the rclone backend is young too. Keep backups of anything irreplaceable.
- The GNOME Files **sidebar** bookmark keeps the generic folder glyph: Nautilus hardcodes bookmark icons, so only the folder in the main view and the app launchers show the Drime logo.
- The Drime logo (`assets/drime.png`) belongs to Drime and is used only to identify the service; it is not covered by this project's MIT license.

## Advanced: install from a git checkout

For other distributions, or to hack on it, without the RPM:

```bash
sudo dnf install python3-gobject gtk4 libadwaita rclone fuse3   # or your distro's equivalents
git clone https://github.com/DaveTheGameDev/drime-desktop-fedora.git
cd drime-desktop-fedora
./install.sh                 # terminal wizard; add --with-pydrime for the CLI, --install-browser to fetch Chromium
PYTHONPATH=src DRIME_DESKTOP_SRC=$PWD python3 -m drime_desktop.cli    # the GUI, from the checkout
```

In this mode the systemd units are copied to `~/.config/systemd/user/`. If you later install the RPM, the app switches to the packaged units automatically. `./uninstall.sh [--purge-config]` reverses the setup.

<details>
<summary>What the setup does, step by step</summary>

1. `rclone config create drime drime access_token=<TOKEN>` and `rclone about drime:` to verify it
2. `systemctl --user enable --now rclone-drime-mount.service` (units from `/usr/lib/systemd/user/` or `systemd/`)
3. Add `~/Drime` to `~/.config/gtk-3.0/bookmarks`; `gio set ~/Drime metadata::custom-icon file:///usr/share/icons/hicolor/512x512/apps/drime-desktop.png`
4. If no Chromium-based browser is found: optionally `flatpak install --user flathub org.chromium.Chromium`
5. `mkdir ~/DrimeSync && touch ~/DrimeSync/RCLONE_TEST && rclone copy ~/DrimeSync/RCLONE_TEST drime:Sync/`
6. `rclone bisync ~/DrimeSync drime:Sync --size-only --create-empty-src-dirs --check-access --resync`
7. `systemctl --user enable --now drime-bisync.timer`

The launchers (`drime-desktop.desktop`, `drime-webapp.desktop`) and the icon are installed system-wide by the package; *Drime Web* runs `drime-desktop --open-web`, which picks the browser at launch time (Flatpak Chromium → Flatpak Brave → chromium → google-chrome).
</details>

## Building the RPM

```bash
sudo dnf install rpm-build rpmdevtools rpmlint python3-devel systemd-rpm-macros desktop-file-utils libappstream-glib
make rpm lint            # -> build/RPMS/noarch/drime-desktop-<version>-1.fc44.noarch.rpm
make install-local       # sudo dnf install it
```

(`make rpm RPMBUILD_OPTS=--nodeps` builds without `python3-devel`.)

**Releasing**: bump `Version:` and `%changelog` in `drime-desktop.spec`, commit, then `git tag v<version> && git push --tags`. The [GitHub Actions workflow](.github/workflows/release.yml) builds the RPM in a Fedora container, lints it and attaches the `.rpm`, `.src.rpm` and source tarball to a GitHub Release. The tag must match the spec version. The app's *Check for updates* reads the latest release through the public GitHub API, so it only sees releases once the repository is public.

## Repo layout

```
drime-desktop.spec          # RPM spec (single source of the version)
Makefile                    # make rpm / lint / install-local
src/drime_desktop/          # Python package: backend (rclone/systemd/flatpak), GTK app, wizard, updates, CLI
bin/drime-desktop           # launcher
systemd/                    # user units: mount service, bisync service + timer
desktop/                    # drime-desktop.desktop (app), drime-webapp.desktop (web window)
assets/                     # icon, AppStream metainfo
install.sh / uninstall.sh   # thin wrappers for git-checkout installs
.github/workflows/          # release build
```

---

*Unofficial project, not affiliated with Drime. Built on [rclone](https://rclone.org/drime/) and [pydrime](https://pydrime.readthedocs.io/).*
