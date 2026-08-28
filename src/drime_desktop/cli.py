"""Command-line entry point. Without arguments the GUI starts."""
from __future__ import annotations

import argparse
import getpass
import os
import sys

from . import __version__, backend


def _print(line: str) -> None:
    print(line, flush=True)


def cmd_install(args) -> int:
    token = None
    if not backend.remote_exists():
        if args.token_from_stdin:
            token = sys.stdin.readline().strip()
        else:
            print("A Drime API token is required.")
            print("Get one at: app.drime.cloud -> Settings -> Developer -> create token")
            token = getpass.getpass("Paste your Drime API token: ")
    try:
        backend.install_all(token, _print, with_pydrime=args.with_pydrime,
                            install_browser=args.install_browser)
    except Exception as e:  # noqa: BLE001 - surface any failure to the user
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    print()
    print("Done. Summary:")
    print(f"  - Virtual drive:  {backend.MOUNT} ({backend.MOUNT_UNIT})")
    print(f"  - Sync folder:    {backend.SYNC_DIR} <-> {backend.SYNC_REMOTE_PATH} every 15 min")
    print("  - Apps:           'Drime' (manage) and 'Drime Web' in your application grid")
    print(f"  - Keep the RCLONE_TEST file in {backend.SYNC_DIR} - it is a safety marker.")
    return 0


def cmd_uninstall(args) -> int:
    backend.uninstall_all(purge_config=args.purge_config, log=_print)
    if backend.ICON_SYSTEM.is_file():
        print("To remove the application itself: sudo dnf remove drime-desktop")
    return 0


def cmd_status(_args) -> int:
    st = backend.state()
    print(f"drime-desktop {__version__}")
    for p in st.problems:
        print(f"PROBLEM: {p}")
    print(f"API token configured: {'yes' if st.remote else 'no'}")
    print(f"Virtual drive:        enabled={st.mount_enabled} active={st.mount_active} mounted={st.mounted}")
    print(f"Sync folder:          enabled={st.sync_enabled} initialized={st.sync_initialized}")
    s = backend.sync_status()
    print(f"Last sync:            {s.last_result or 'never'} (ended {s.last_end or '-'}), next {s.next_run or '-'}")
    print(f"Browser:              {st.browser.name if st.browser else 'none found'}")
    print(f"Units:                {'packaged' if st.packaged_units else 'user'}"
          + (f", user copies present: {', '.join(st.user_unit_copies)}" if st.user_unit_copies else ""))
    return 0


def cmd_open_web(_args) -> int:
    browser = backend.find_browser()
    if browser is not None:
        os.execvp(browser.cmd[0], backend.browser_cmd(browser))
    if os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"):
        from .app import run_gui
        return run_gui(notice="No Chromium-based browser was found. Install one to open the web app.")
    print("No Chromium-based browser found. Install Chromium (e.g. flatpak install flathub org.chromium.Chromium).",
          file=sys.stderr)
    return 1


def cmd_check_update(_args) -> int:
    from . import updates
    try:
        rel = updates.fetch_latest()
    except updates.UpdateError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    if rel is None:
        print(f"Installed {__version__}; no releases published yet.")
        return 0
    if updates.is_newer(rel.version, __version__):
        print(f"Update available: {rel.version} (installed {__version__})")
        print(rel.rpm_url or rel.html_url)
        return 10
    print(f"Up to date ({__version__}).")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="drime-desktop",
                                description="Unofficial Drime cloud desktop integration. "
                                            "Without options, opens the graphical app.")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--install", action="store_true", help="set up everything from the terminal")
    g.add_argument("--uninstall", action="store_true", help="remove the setup (keeps ~/DrimeSync)")
    g.add_argument("--status", action="store_true", help="print the current state")
    g.add_argument("--open-web", action="store_true", help="open app.drime.cloud in an app window")
    g.add_argument("--check-update", action="store_true", help="check GitHub for a newer release")
    p.add_argument("--token-from-stdin", action="store_true", help="(--install) read the API token from stdin")
    p.add_argument("--with-pydrime", action="store_true", help="(--install) also install the pydrime CLI")
    p.add_argument("--install-browser", action="store_true",
                   help="(--install) install Chromium (Flatpak) when no browser is found")
    p.add_argument("--purge-config", action="store_true",
                   help="(--uninstall) also delete the API token and pydrime config")
    args = p.parse_args(argv)

    if args.install:
        return cmd_install(args)
    if args.uninstall:
        return cmd_uninstall(args)
    if args.status:
        return cmd_status(args)
    if args.open_web:
        return cmd_open_web(args)
    if args.check_update:
        return cmd_check_update(args)
    from .app import run_gui
    return run_gui()


if __name__ == "__main__":
    sys.exit(main())
