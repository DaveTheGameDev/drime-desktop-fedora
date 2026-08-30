"""Update check against GitHub Releases, download and install through PackageKit."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import GITHUB_REPO, __version__

API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
RELEASES_URL = f"https://github.com/{GITHUB_REPO}/releases"
PREFS = Path.home() / ".config/drime-desktop/updates.json"


class UpdateError(Exception):
    pass


@dataclass
class Release:
    version: str
    rpm_url: str | None
    html_url: str


def fetch_latest() -> Release | None:
    """Latest release, or None when the repo has no (visible) releases."""
    req = urllib.request.Request(API_URL, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": f"drime-desktop/{__version__}",
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        if e.code in (403, 429):
            raise UpdateError("GitHub rate limit reached, try again later.") from e
        raise UpdateError(f"GitHub returned HTTP {e.code}.") from e
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        raise UpdateError("Could not reach GitHub. Are you online?") from e
    version = data.get("tag_name", "").lstrip("v")
    asset = next((a for a in data.get("assets", []) if a["name"].endswith(".noarch.rpm")), None)
    return Release(version, asset["browser_download_url"] if asset else None, data.get("html_url", RELEASES_URL))


def _version_key(v: str) -> tuple:
    return tuple(int(x) if x.isdigit() else 0 for x in re.split(r"[.\-+~]", v))


def is_newer(latest: str, installed: str) -> bool:
    try:
        import rpm  # python3-rpm, normally present on Fedora
        return rpm.labelCompare(("0", latest, "0"), ("0", installed, "0")) > 0
    except ImportError:
        return _version_key(latest) > _version_key(installed)


def download_rpm(url: str, progress: Callable[[int, int], None] | None = None) -> Path:
    dest_dir = Path(subprocess.run(["xdg-user-dir", "DOWNLOAD"], capture_output=True,
                                   text=True).stdout.strip() or (Path.home() / "Downloads"))
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / url.rsplit("/", 1)[-1]
    req = urllib.request.Request(url, headers={"User-Agent": f"drime-desktop/{__version__}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r, open(dest, "wb") as f:
            total = int(r.headers.get("Content-Length") or 0)
            done = 0
            while chunk := r.read(64 * 1024):
                f.write(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
    except (urllib.error.URLError, OSError) as e:
        raise UpdateError(f"Download failed: {e}") from e
    return dest


def install_rpm(path: Path, progress: Callable[[int], None] | None = None) -> None:
    """Install (upgrade to) the RPM through PackageKit; polkit asks for the password.

    Runs in a worker thread: the PackageKit call is synchronous. Raises UpdateError
    with a readable message when the user cancels the authorisation or the
    transaction fails."""
    try:
        import gi
        gi.require_version("PackageKitGlib", "1.0")
        from gi.repository import GLib, PackageKitGlib as PK
    except (ImportError, ValueError) as e:
        raise UpdateError("PackageKit is not available on this system.") from e

    def on_progress(prog, kind, _data):
        if progress and kind == PK.ProgressType.PERCENTAGE and prog.props.percentage >= 0:
            progress(prog.props.percentage)

    try:
        # NONE (not ONLY_TRUSTED): release RPMs are unsigned, so this needs the
        # "install untrusted package" polkit action.
        res = PK.Client().install_files(PK.TransactionFlagEnum.NONE, [str(path)], None, on_progress, None)
    except GLib.Error as e:
        if e.matches(PK.client_error_quark(), PK.ClientError.FAILED_AUTH) or "not authorized" in e.message.lower():
            raise UpdateError("Installation cancelled: not authorised.") from e
        raise UpdateError(f"Installation failed: {e.message}") from e
    err = res.get_error_code()
    if err is not None:
        if err.get_code() == PK.ErrorEnum.NOT_AUTHORIZED:
            raise UpdateError("Installation cancelled: not authorised.")
        raise UpdateError(f"Installation failed: {err.get_details()}")


def open_for_install(path: Path) -> None:
    """Fallback without PackageKit: open the RPM in GNOME Software / the default handler."""
    if shutil.which("gnome-software"):
        cmd = ["gnome-software", f"--local-filename={path}"]
    else:
        cmd = ["gio", "open", str(path)]
    subprocess.Popen(cmd, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def installed_version() -> str | None:
    """Version of the package files currently on disk (None from a git checkout).

    Differs from __version__ once an RPM upgrade has replaced the files under a
    running app, which keeps executing the old code until it is restarted."""
    try:
        text = (Path(__file__).resolve().parent / "__init__.py").read_text()
    except OSError:
        return None
    m = re.search(r'^__version__ = "([^"@]+)"', text, re.M)
    return m.group(1) if m else None


def restart_app() -> None:
    """Relaunch after this (single-instance) process has exited, then quit is up to the caller."""
    exe = shutil.which("drime-desktop")
    cmd = [exe] if exe else [sys.executable, "-c", "import sys; from drime_desktop.cli import main; sys.exit(main())"]
    waiter = (f"while kill -0 {os.getpid()} 2>/dev/null; do sleep 0.2; done; "
              + "exec " + " ".join(subprocess.list2cmdline([c]) for c in cmd))
    subprocess.Popen(["sh", "-c", waiter], start_new_session=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _prefs() -> dict:
    try:
        return json.loads(PREFS.read_text())
    except (OSError, ValueError):
        return {}


def skipped_version() -> str | None:
    """Version the user chose to skip in the startup prompt, if any."""
    return _prefs().get("skip")


def skip_version(version: str) -> None:
    try:
        PREFS.parent.mkdir(parents=True, exist_ok=True)
        PREFS.write_text(json.dumps({**_prefs(), "skip": version}))
    except OSError:
        pass


def open_releases_page() -> None:
    subprocess.Popen(["gio", "open", RELEASES_URL], start_new_session=True)
