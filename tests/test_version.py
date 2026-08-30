"""The version comes from the spec in a checkout and from the stamped __init__.py in a package."""
import re
import shutil
import subprocess
import sys
from pathlib import Path

import drime_desktop
from drime_desktop import updates

ROOT = Path(__file__).resolve().parents[1]


def spec_version() -> str:
    return re.search(r"^Version:\s*(\S+)", (ROOT / "drime-desktop.spec").read_text(), re.M).group(1)


def test_checkout_reads_version_from_spec():
    assert drime_desktop.__version__ == spec_version()


def test_checkout_has_no_installed_version():
    assert updates.installed_version() is None


def test_stamped_package_reports_its_version(tmp_path):
    """What the RPM and DEB builds do: substitute @VERSION@ in __init__.py."""
    pkg = tmp_path / "drime_desktop"
    shutil.copytree(ROOT / "src" / "drime_desktop", pkg)
    init = pkg / "__init__.py"
    init.write_text(init.read_text().replace("@VERSION@", "1.2.3"))
    out = subprocess.run(
        [sys.executable, "-c",
         "import drime_desktop, drime_desktop.updates as u; print(drime_desktop.__version__, u.installed_version())"],
        cwd=tmp_path, env={"PYTHONPATH": str(tmp_path), "PATH": "/usr/bin:/bin"},
        capture_output=True, text=True, check=True)
    assert out.stdout.split() == ["1.2.3", "1.2.3"]


def test_changelog_starts_with_current_version():
    text = (ROOT / "drime-desktop.spec").read_text()
    first = re.search(r"^\* .* - (\S+)-\d+$", text[text.index("%changelog"):], re.M).group(1)
    assert first == spec_version()
