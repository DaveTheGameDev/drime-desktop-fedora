"""Update check against GitHub Releases and hand-off to GNOME Software."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import GITHUB_REPO, __version__

API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
RELEASES_URL = f"https://github.com/{GITHUB_REPO}/releases"


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


def open_for_install(path: Path) -> None:
    """Open the RPM in GNOME Software (PackageKit local install)."""
    if shutil.which("gnome-software"):
        cmd = ["gnome-software", f"--local-filename={path}"]
    else:
        cmd = ["gio", "open", str(path)]
    subprocess.Popen(cmd, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def open_releases_page() -> None:
    subprocess.Popen(["gio", "open", RELEASES_URL], start_new_session=True)
