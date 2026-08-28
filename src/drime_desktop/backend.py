"""All system-level operations (rclone, systemd, flatpak, files).

Pure Python + subprocess. No GTK imports, so it is usable from the CLI, the
GUI, and tests. Every function is idempotent where it makes sense.
"""
from __future__ import annotations

import glob
import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

HOME = Path.home()
REMOTE = "drime"
MOUNT = HOME / "Drime"
SYNC_DIR = HOME / "DrimeSync"
SYNC_REMOTE_PATH = f"{REMOTE}:Sync"
USER_UNIT_DIR = HOME / ".config/systemd/user"
SYSTEM_UNIT_DIR = Path("/usr/lib/systemd/user")
MOUNT_UNIT = "rclone-drime-mount.service"
SYNC_SERVICE = "drime-bisync.service"
SYNC_TIMER = "drime-bisync.timer"
UNITS = (MOUNT_UNIT, SYNC_SERVICE, SYNC_TIMER)
MIN_RCLONE = (1, 73, 0)
WEB_URL = "https://app.drime.cloud"
ICON_SYSTEM = Path("/usr/share/icons/hicolor/512x512/apps/drime-desktop.png")
ICON_USER = HOME / ".local/share/icons/drime.png"
LEGACY_LAUNCHER = HOME / ".local/share/applications/drime.desktop"
BOOKMARKS = HOME / ".config/gtk-3.0/bookmarks"
RCLONE_CACHE = HOME / ".cache/rclone"
CHROMIUM_FLATPAK = "org.chromium.Chromium"
FLATHUB_REPO = "https://dl.flathub.org/repo/flathub.flatpakrepo"

# Set by install.sh/uninstall.sh when running from a git checkout (no RPM).
SRC_DIR = Path(os.environ["DRIME_DESKTOP_SRC"]) if os.environ.get("DRIME_DESKTOP_SRC") else None

LogCb = Callable[[str], None]


def _noop(_line: str) -> None:
    pass


def run(cmd: list[str], check: bool = False, **kw) -> subprocess.CompletedProcess:
    kw.setdefault("capture_output", True)
    kw.setdefault("text", True)
    return subprocess.run(cmd, check=check, **kw)


def run_logged(cmd: list[str], log: LogCb = _noop) -> int:
    """Run a command, streaming its combined output line by line to `log`."""
    log("$ " + " ".join(cmd))
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    assert proc.stdout is not None
    for line in proc.stdout:
        log(line.rstrip("\n"))
    return proc.wait()


def systemctl(*args: str, check: bool = False) -> subprocess.CompletedProcess:
    return run(["systemctl", "--user", *args], check=check)


# --- Preflight ---------------------------------------------------------------

def rclone_version() -> tuple[int, ...] | None:
    if not shutil.which("rclone"):
        return None
    out = run(["rclone", "version"]).stdout
    m = re.search(r"rclone v(\d+)\.(\d+)(?:\.(\d+))?", out)
    if not m:
        return None
    return tuple(int(x or 0) for x in m.groups())


def preflight() -> list[str]:
    """Return a list of human-readable blocking problems (empty = all good)."""
    problems = []
    ver = rclone_version()
    if ver is None:
        problems.append("rclone is not installed (sudo dnf install rclone).")
    elif ver < MIN_RCLONE:
        problems.append(
            "rclone %s is too old; the Drime backend needs %s or newer (sudo dnf upgrade rclone)."
            % (".".join(map(str, ver)), ".".join(map(str, MIN_RCLONE))))
    if not shutil.which("fusermount3"):
        problems.append("fuse3 is not installed (sudo dnf install fuse3).")
    if systemctl("is-system-running").returncode not in (0, 1):
        # 1 = "degraded", which is still a working user session
        problems.append("No systemd user session is available.")
    return problems


# --- rclone remote (API token) -----------------------------------------------

def remote_exists() -> bool:
    return f"{REMOTE}:" in run(["rclone", "listremotes"]).stdout.split()


def create_remote(token: str) -> None:
    token = token.strip()
    if not token:
        raise ValueError("No token provided.")
    cp = run(["rclone", "config", "create", REMOTE, "drime", f"access_token={token}"])
    if cp.returncode != 0:
        raise RuntimeError(cp.stderr.strip() or "rclone config create failed")


def check_remote() -> bool:
    """True when Drime can be reached with the configured token."""
    return run(["rclone", "about", f"{REMOTE}:", "--contimeout", "15s"]).returncode == 0


def delete_remote() -> None:
    run(["rclone", "config", "delete", REMOTE])


# --- systemd units -----------------------------------------------------------

def is_enabled(unit: str) -> bool:
    return systemctl("is-enabled", unit).returncode == 0


def is_active(unit: str) -> bool:
    return systemctl("is-active", unit).returncode == 0


def unit_source(unit: str) -> str:
    """'packaged' (/usr/lib/systemd/user), 'user' (~/.config/systemd/user) or 'none'."""
    frag = systemctl("show", "-p", "FragmentPath", "--value", unit).stdout.strip()
    if not frag:
        return "none"
    if frag.startswith(str(USER_UNIT_DIR)):
        return "user"
    return "packaged"


def packaged_units_available() -> bool:
    return all((SYSTEM_UNIT_DIR / u).is_file() for u in UNITS)


def user_unit_copies() -> list[str]:
    return [u for u in UNITS if (USER_UNIT_DIR / u).exists()]


def migrate_user_units(log: LogCb = _noop) -> bool:
    """Replace ~/.config/systemd/user copies with the packaged units.

    Running services keep running; only the unit files and enable-symlinks are
    swapped. Returns True when something was migrated.
    """
    copies = user_unit_copies()
    if not copies or not packaged_units_available():
        return False
    log("Migrating systemd units to the packaged versions")
    enabled = [u for u in (MOUNT_UNIT, SYNC_TIMER) if is_enabled(u)]
    for u in enabled:
        systemctl("disable", u)  # without --now: keep the mount alive
    for u in copies:
        (USER_UNIT_DIR / u).unlink()
    systemctl("daemon-reload")
    for u in enabled:
        systemctl("enable", u)
    return True


def ensure_units(log: LogCb = _noop) -> None:
    """Make sure the three units are known to systemd (packaged or user copies)."""
    if packaged_units_available():
        migrate_user_units(log)
    else:
        if SRC_DIR is None or not (SRC_DIR / "systemd" / MOUNT_UNIT).is_file():
            raise RuntimeError("systemd units not found: install the RPM or run from a git checkout.")
        USER_UNIT_DIR.mkdir(parents=True, exist_ok=True)
        for u in UNITS:
            shutil.copy(SRC_DIR / "systemd" / u, USER_UNIT_DIR / u)
        log(f"Installed units to {USER_UNIT_DIR}")
    systemctl("daemon-reload")


# --- Virtual drive -----------------------------------------------------------

def is_mounted() -> bool:
    try:
        with open("/proc/mounts") as f:
            target = str(MOUNT).replace(" ", "\\040")
            return any(line.split()[1] == target for line in f)
    except OSError:
        return False


def mount_enable(log: LogCb = _noop) -> None:
    ensure_units(log)
    cp = systemctl("enable", "--now", MOUNT_UNIT)
    if cp.returncode != 0:
        raise RuntimeError(cp.stderr.strip() or "Could not start the mount service")
    log(f"Virtual drive mounted at {MOUNT}")


def mount_disable(log: LogCb = _noop) -> None:
    systemctl("disable", "--now", MOUNT_UNIT)
    if is_mounted():
        run(["fusermount3", "-u", str(MOUNT)])
    log("Virtual drive disabled")


def bookmark_add() -> None:
    BOOKMARKS.parent.mkdir(parents=True, exist_ok=True)
    line = f"file://{MOUNT} Drime\n"
    existing = BOOKMARKS.read_text() if BOOKMARKS.exists() else ""
    if f"file://{MOUNT} " not in existing:
        with BOOKMARKS.open("a") as f:
            f.write(line)


def bookmark_remove() -> None:
    if BOOKMARKS.exists():
        lines = [l for l in BOOKMARKS.read_text().splitlines(True)
                 if not l.startswith(f"file://{MOUNT} ")]
        BOOKMARKS.write_text("".join(lines))


def icon_path() -> Path | None:
    if ICON_SYSTEM.is_file():
        return ICON_SYSTEM
    if SRC_DIR is not None and (SRC_DIR / "assets/drime.png").is_file():
        ICON_USER.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(SRC_DIR / "assets/drime.png", ICON_USER)
    return ICON_USER if ICON_USER.is_file() else None


def folder_icon_set() -> bool:
    icon = icon_path()
    if icon is None or not MOUNT.is_dir():
        return False
    return run(["gio", "set", str(MOUNT), "metadata::custom-icon", f"file://{icon}"]).returncode == 0


def folder_icon_unset() -> None:
    run(["gio", "set", "-t", "unset", str(MOUNT), "metadata::custom-icon"])


# --- Web app / browser -------------------------------------------------------

@dataclass(frozen=True)
class Browser:
    name: str
    cmd: tuple[str, ...]
    flatpak_id: str | None = None


_BROWSERS = (
    ("Chromium (Flatpak)", ("flatpak", "run", CHROMIUM_FLATPAK), CHROMIUM_FLATPAK),
    ("Brave (Flatpak)", ("flatpak", "run", "com.brave.Browser"), "com.brave.Browser"),
    ("Chromium", ("chromium",), None),
    ("Chromium", ("chromium-browser",), None),
    ("Google Chrome", ("google-chrome",), None),
)


def flatpak_installed(app_id: str) -> bool:
    return bool(shutil.which("flatpak")) and run(["flatpak", "info", app_id]).returncode == 0


def find_browser() -> Browser | None:
    for name, cmd, fp in _BROWSERS:
        if fp is not None:
            if flatpak_installed(fp):
                return Browser(name, cmd, fp)
        elif shutil.which(cmd[0]):
            return Browser(name, cmd, None)
    return None


def browser_cmd(browser: Browser, url: str = WEB_URL) -> list[str]:
    return [*browser.cmd, f"--app={url}"]


def open_web_app(browser: Browser) -> None:
    subprocess.Popen(browser_cmd(browser), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)


def install_chromium_flatpak(log: LogCb = _noop) -> bool:
    if not shutil.which("flatpak"):
        log("flatpak is not installed (sudo dnf install flatpak)")
        return False
    rc = run_logged(["flatpak", "remote-add", "--user", "--if-not-exists", "flathub", FLATHUB_REPO], log)
    if rc != 0:
        return False
    rc = run_logged(["flatpak", "install", "--user", "-y", "--noninteractive", "flathub", CHROMIUM_FLATPAK], log)
    return rc == 0


def update_browser_flatpak(browser: Browser, log: LogCb = _noop) -> bool:
    if browser.flatpak_id is None:
        log("The browser is not a Flatpak; update it with your system updates.")
        return False
    return run_logged(["flatpak", "update", "-y", "--noninteractive", browser.flatpak_id], log) == 0


def open_in_software(app_id: str) -> bool:
    if not shutil.which("gnome-software"):
        return False
    subprocess.Popen(["gnome-software", f"--details={app_id}"], start_new_session=True)
    return True


# --- Sync folder -------------------------------------------------------------

def bisync_initialized() -> bool:
    return bool(glob.glob(str(RCLONE_CACHE / "bisync" / "*DrimeSync*")))


def bisync_baseline(log: LogCb = _noop) -> None:
    SYNC_DIR.mkdir(parents=True, exist_ok=True)
    (SYNC_DIR / "RCLONE_TEST").touch()
    if bisync_initialized():
        log("Sync already initialized, skipping the baseline run")
        return
    if run_logged(["rclone", "copy", str(SYNC_DIR / "RCLONE_TEST"), SYNC_REMOTE_PATH + "/"], log) != 0:
        raise RuntimeError("Could not upload the RCLONE_TEST marker")
    rc = run_logged(["rclone", "bisync", str(SYNC_DIR), SYNC_REMOTE_PATH, "--size-only",
                     "--create-empty-src-dirs", "--check-access", "--resync"], log)
    if rc != 0:
        raise RuntimeError("The initial sync (bisync --resync) failed; see the log")
    log("Sync baseline established")


def sync_enable(log: LogCb = _noop) -> None:
    ensure_units(log)
    bisync_baseline(log)
    cp = systemctl("enable", "--now", SYNC_TIMER)
    if cp.returncode != 0:
        raise RuntimeError(cp.stderr.strip() or "Could not enable the sync timer")
    log("Sync timer enabled (every 15 minutes)")


def sync_disable(log: LogCb = _noop) -> None:
    systemctl("disable", "--now", SYNC_TIMER)
    log("Sync timer disabled")


def sync_now() -> None:
    systemctl("start", "--no-block", SYNC_SERVICE)


@dataclass
class SyncStatus:
    running: bool
    last_result: str          # success / exit-code / '' when never run
    last_start: int | None    # unix seconds
    last_end: int | None
    next_run: int | None


def _unix(value: str) -> int | None:
    value = value.strip()
    if value.startswith("@"):
        return int(value[1:])
    return None


def sync_status() -> SyncStatus:
    out = systemctl("show", SYNC_SERVICE, "--timestamp=unix", "-p",
                    "ActiveState,Result,ExecMainStartTimestamp,ExecMainExitTimestamp").stdout
    props = dict(line.split("=", 1) for line in out.splitlines() if "=" in line)
    next_run = None
    lt = run(["systemctl", "--user", "list-timers", SYNC_TIMER, "--output=json", "--all"])
    try:
        for t in json.loads(lt.stdout or "[]"):
            if t.get("unit") == SYNC_TIMER and t.get("next"):
                next_run = int(t["next"]) // 1_000_000
    except (ValueError, TypeError):
        pass
    return SyncStatus(
        running=props.get("ActiveState") in ("active", "activating"),
        last_result=props.get("Result", ""),
        last_start=_unix(props.get("ExecMainStartTimestamp", "")),
        last_end=_unix(props.get("ExecMainExitTimestamp", "")),
        next_run=next_run,
    )


def sync_log_tail(lines: int = 60) -> str:
    return run(["journalctl", "--user", "-u", SYNC_SERVICE, "-n", str(lines),
                "--no-pager", "-o", "short-iso"]).stdout


# --- Aggregate state ---------------------------------------------------------

@dataclass
class State:
    problems: list[str]
    remote: bool
    mount_enabled: bool
    mount_active: bool
    mounted: bool
    sync_enabled: bool
    sync_initialized: bool
    browser: Browser | None
    user_unit_copies: list[str]
    packaged_units: bool

    @property
    def configured(self) -> bool:
        return self.remote and self.mount_enabled and self.sync_enabled


def state() -> State:
    return State(
        problems=preflight(),
        remote=remote_exists(),
        mount_enabled=is_enabled(MOUNT_UNIT),
        mount_active=is_active(MOUNT_UNIT),
        mounted=is_mounted(),
        sync_enabled=is_enabled(SYNC_TIMER),
        sync_initialized=bisync_initialized(),
        browser=find_browser(),
        user_unit_copies=user_unit_copies(),
        packaged_units=packaged_units_available(),
    )


def cleanup_legacy() -> bool:
    """Remove the per-user launcher/icon written by the old install.sh
    (they duplicate the packaged ones). Returns True if anything was removed."""
    if not ICON_SYSTEM.is_file():
        return False
    removed = False
    if LEGACY_LAUNCHER.exists():
        LEGACY_LAUNCHER.unlink()
        run(["update-desktop-database", str(LEGACY_LAUNCHER.parent)])
        removed = True
    if ICON_USER.exists():
        ICON_USER.unlink()
        folder_icon_set()  # re-point the folder icon at the system icon
        removed = True
    return removed


# --- Full install / uninstall (CLI and wizard share these) --------------------

def install_all(token: str | None, log: LogCb = _noop, with_pydrime: bool = False,
                install_browser: bool = False) -> None:
    problems = preflight()
    if problems:
        raise RuntimeError("\n".join(problems))
    if not remote_exists():
        if not token:
            raise RuntimeError("A Drime API token is required.")
        create_remote(token)
        log(f"Remote '{REMOTE}:' created")
    if not check_remote():
        raise RuntimeError("Cannot reach Drime with the configured token.")
    log("Drime account reachable")

    mount_enable(log)
    bookmark_add()
    if folder_icon_set():
        log("Drime icon applied to the folder")
    cleanup_legacy()

    if find_browser() is None:
        if install_browser:
            install_chromium_flatpak(log)
        else:
            log("WARNING: no Chromium-based browser found; the web app launcher needs one.")

    sync_enable(log)

    if with_pydrime:
        run_logged(["python3", "-m", "pip", "install", "--user", "--quiet", "pydrime"], log)
        log("pydrime installed - run 'pydrime init' and paste the same API token")


def uninstall_all(purge_config: bool = False, log: LogCb = _noop) -> None:
    folder_icon_unset()
    systemctl("disable", "--now", SYNC_TIMER)
    systemctl("stop", SYNC_SERVICE)
    systemctl("disable", "--now", MOUNT_UNIT)
    if is_mounted():
        run(["fusermount3", "-u", str(MOUNT)])
    for u in UNITS:
        (USER_UNIT_DIR / u).unlink(missing_ok=True)
    systemctl("daemon-reload")
    systemctl("reset-failed")
    log("Drive unmounted, services disabled")

    if LEGACY_LAUNCHER.exists():
        LEGACY_LAUNCHER.unlink()
        run(["update-desktop-database", str(LEGACY_LAUNCHER.parent)])
    ICON_USER.unlink(missing_ok=True)
    bookmark_remove()
    log("Launcher, icon and file-manager bookmark removed")

    shutil.rmtree(RCLONE_CACHE / "vfs" / REMOTE, ignore_errors=True)
    shutil.rmtree(RCLONE_CACHE / "vfsMeta" / REMOTE, ignore_errors=True)
    for p in glob.glob(str(RCLONE_CACHE / "bisync" / "*DrimeSync*")):
        Path(p).unlink(missing_ok=True)
    try:
        MOUNT.rmdir()
    except OSError:
        pass
    log("rclone caches and sync state removed")

    if purge_config:
        delete_remote()
        shutil.rmtree(HOME / ".config/pydrime", ignore_errors=True)
        run(["python3", "-m", "pip", "uninstall", "-y", "-q", "pydrime"])
        log("API token (rclone remote) and pydrime configuration removed")
    log(f"Kept: {SYNC_DIR} and everything in your cloud account")
