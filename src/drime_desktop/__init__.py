"""Unofficial Drime cloud desktop integration for Linux."""
import os
import re
from pathlib import Path

__version__ = "@VERSION@"

if __version__.startswith("@"):
    # Running from a git checkout: read the version from the spec file.
    __version__ = "0.0.0"
    _spec = Path(__file__).resolve().parents[2] / "drime-desktop.spec"
    if _spec.is_file():
        _m = re.search(r"^Version:\s*(\S+)", _spec.read_text(), re.M)
        if _m:
            __version__ = _m.group(1)

# Lets you test the update check ("DRIME_DESKTOP_VERSION_OVERRIDE=0.0.1 drime-desktop").
__version__ = os.environ.get("DRIME_DESKTOP_VERSION_OVERRIDE", __version__)

APP_ID = "io.github.davethegamedev.DrimeDesktop"
GITHUB_REPO = "DaveTheGameDev/drime-desktop-linux"
