import shutil
import subprocess

import pytest

from drime_desktop import backend


@pytest.mark.parametrize("os_release, expected", [
    ('ID=ubuntu\nID_LIKE=debian\n', "debian"),
    ('ID=debian\n', "debian"),
    ('ID=linuxmint\nID_LIKE="ubuntu debian"\n', "debian"),
    ('ID=fedora\n', "fedora"),
    ('ID="rhel"\nID_LIKE="fedora"\n', "fedora"),
    ('ID=arch\n', "unknown"),
])
def test_distro_from_os_release(monkeypatch, tmp_path, os_release, expected):
    f = tmp_path / "os-release"
    f.write_text(f'NAME="Something"\n{os_release}VERSION_ID="1"\n')
    monkeypatch.setattr(backend, "OS_RELEASE", f)
    assert backend.distro() == expected


def test_distro_without_os_release(monkeypatch, tmp_path):
    monkeypatch.setattr(backend, "OS_RELEASE", tmp_path / "missing")
    assert backend.distro() == "unknown"


def test_hints_fedora(fake_distro):
    fake_distro("fedora")
    assert backend.install_hint("fuse3") == "sudo dnf install fuse3"
    assert backend.install_hint("rclone") == "sudo dnf install rclone"
    assert backend.install_hint("rclone", upgrade=True) == "sudo dnf upgrade rclone"
    assert backend.remove_hint() == "sudo dnf remove drime-desktop"


def test_hints_debian(fake_distro):
    fake_distro("debian")
    assert backend.install_hint("fuse3") == "sudo apt install fuse3"
    # The archive's rclone is too old for the Drime backend, so point at rclone.org.
    assert "rclone.org" in backend.install_hint("rclone")
    assert "rclone.org" in backend.install_hint("rclone", upgrade=True)
    assert backend.remove_hint() == "sudo apt remove drime-desktop"


def test_hints_unknown(fake_distro):
    fake_distro("unknown")
    assert "fuse3" in backend.install_hint("fuse3")
    assert "drime-desktop" in backend.remove_hint()


@pytest.fixture
def broken_system(monkeypatch):
    """rclone and fuse3 missing, systemd user session fine."""
    monkeypatch.setattr(backend, "rclone_version", lambda: None)
    monkeypatch.setattr(shutil, "which", lambda name: None)
    monkeypatch.setattr(backend, "systemctl",
                        lambda *a, **k: subprocess.CompletedProcess(a, 0, "", ""))


def test_preflight_wording_debian(broken_system, fake_distro):
    fake_distro("debian")
    problems = backend.preflight()
    assert len(problems) == 2
    assert problems[0].startswith("rclone is not installed") and "rclone.org" in problems[0]
    assert problems[1] == "fuse3 is not installed (sudo apt install fuse3)."


def test_preflight_wording_fedora(broken_system, fake_distro):
    fake_distro("fedora")
    assert backend.preflight() == [
        "rclone is not installed (sudo dnf install rclone).",
        "fuse3 is not installed (sudo dnf install fuse3).",
    ]


def test_preflight_old_rclone(broken_system, fake_distro, monkeypatch):
    monkeypatch.setattr(backend, "rclone_version", lambda: (1, 60, 1))
    fake_distro("debian")
    msg = backend.preflight()[0]
    assert msg.startswith("rclone 1.60.1 is too old; the Drime backend needs 1.73.0 or newer")
    assert "rclone.org" in msg
    fake_distro("fedora")
    assert "(sudo dnf upgrade rclone)" in backend.preflight()[0]


def _fake_proc(tmp_path, procs):
    """procs: {pid: (comm, ppid)} -> a /proc look-alike with stat files."""
    for pid, (comm, ppid) in procs.items():
        d = tmp_path / str(pid)
        d.mkdir()
        (d / "stat").write_text(f"{pid} ({comm}) S {ppid} {pid} {pid} 0 -1 4194560 0\n")
    (tmp_path / "self").mkdir()
    (tmp_path / "meminfo").write_text("MemTotal: 1 kB\n")
    return tmp_path


def test_child_pids_matches_truncated_comm_of_direct_children(tmp_path):
    proc = _fake_proc(tmp_path, {
        100: ("drime-desktop", 1),
        101: ("WebKitNetworkPr", 100),   # /proc truncates the name to 15 chars
        102: ("bwrap", 100),
        103: ("WebKitWebProces", 102),   # grandchild through the sandbox
        104: ("WebKitNetworkPr", 999),   # another app's
        105: ("WebKit (odd) Pr", 100),   # parentheses in the name must not confuse the parser
    })
    assert backend.child_pids("WebKitNetworkProcess", proc, parent=100) == [101]
    assert backend.child_pids("WebKitWebProcess", proc, parent=100) == []
    assert backend.child_pids("WebKitWebProcess", proc, parent=102) == [103]


def test_child_pids_skips_unreadable_entries(tmp_path):
    proc = _fake_proc(tmp_path, {100: ("WebKitNetworkPr", 7)})
    (tmp_path / "200").mkdir()                      # vanished before its stat was read
    (tmp_path / "300").mkdir()
    (tmp_path / "300" / "stat").write_text("garbage")
    assert backend.child_pids("WebKitNetworkProcess", proc, parent=7) == [100]
