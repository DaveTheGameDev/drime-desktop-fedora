import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from drime_desktop import backend  # noqa: E402


@pytest.fixture
def fake_distro(monkeypatch):
    """Pretend to run on a given distribution family: fake_distro("debian")."""
    def set_distro(name: str):
        monkeypatch.setattr(backend, "distro", lambda: name)
    return set_distro
