"""The embedded Drime web app (WebKitGTK 6 / GTK4).

DrimeWebView wraps a WebKit.WebView with: persistent login (cookies and local
storage under ~/.local/share/drime-desktop), downloads into ~/Downloads,
links that ask for a new window opened in the system browser, an offline
overlay with Retry, and zoom shortcuts.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("WebKit", "6.0")
from gi.repository import Adw, GLib, GObject, Gtk, WebKit  # noqa: E402

from . import __version__, backend  # noqa: E402


def downloads_dir() -> Path:
    d = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_DOWNLOAD)
    return Path(d) if d else Path.home() / "Downloads"


def unique_path(directory: Path, name: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    p = directory / (name or "download")
    stem, suffix, n = p.stem, p.suffix, 1
    while p.exists():
        n += 1
        p = directory / f"{stem} ({n}){suffix}"
    return p


def open_externally(uri: str, parent: Gtk.Window | None = None) -> None:
    Gtk.UriLauncher.new(uri).launch(parent, None, None)


class DrimeWebView(Gtk.Overlay):
    """WebView + offline overlay. `on_download(path)` is called when a file was saved."""

    def __init__(self, on_download: Callable[[Path], None] | None = None,
                 on_download_failed: Callable[[str], None] | None = None):
        super().__init__()
        self.on_download = on_download
        self.on_download_failed = on_download_failed

        backend.WEB_DATA_DIR.mkdir(parents=True, exist_ok=True)
        backend.WEB_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        self.session = WebKit.NetworkSession.new(str(backend.WEB_DATA_DIR), str(backend.WEB_CACHE_DIR))
        cookies = self.session.get_cookie_manager()
        cookies.set_persistent_storage(str(backend.WEB_DATA_DIR / "cookies.sqlite"),
                                       WebKit.CookiePersistentStorage.SQLITE)
        cookies.set_accept_policy(WebKit.CookieAcceptPolicy.NO_THIRD_PARTY)
        self.session.connect("download-started", self._download_started)

        self.view = WebKit.WebView(network_session=self.session, hexpand=True, vexpand=True)
        settings = self.view.get_settings()
        settings.set_enable_developer_extras(True)
        settings.set_enable_webgl(True)
        settings.set_enable_media_stream(True)
        settings.set_user_agent_with_application_details("DrimeDesktop", __version__)
        self.view.connect("decide-policy", self._decide_policy)
        self.view.connect("create", self._create)
        self.view.connect("load-changed", self._load_changed)
        self.view.connect("load-failed", self._load_failed)
        self.set_child(self.view)

        # Offline / error overlay
        self.offline = Adw.StatusPage(title="Can't reach Drime", icon_name="network-offline-symbolic",
                                      description="Check your internet connection and try again. "
                                                  "Your drive and sync folder keep working from the menu.")
        retry = Gtk.Button(label="Retry", halign=Gtk.Align.CENTER, css_classes=["pill", "suggested-action"])
        retry.connect("clicked", lambda _b: self.reload())
        self.offline.set_child(retry)
        self.offline.add_css_class("background")
        self.offline.set_visible(False)
        self.add_overlay(self.offline)

        self.progress = Gtk.ProgressBar(valign=Gtk.Align.START, css_classes=["osd"], visible=False)
        self.view.bind_property("estimated-load-progress", self.progress, "fraction",
                                GObject.BindingFlags.SYNC_CREATE)
        self.add_overlay(self.progress)

        self._failed = False
        self.load()

    # --- navigation ------------------------------------------------------

    def load(self, url: str = backend.WEB_URL) -> None:
        self._failed = False
        self.view.load_uri(url)

    def reload(self) -> None:
        self._failed = False
        self.offline.set_visible(False)
        if self.view.get_uri():
            self.view.reload()
        else:
            self.load()

    def zoom(self, delta: float | None) -> None:
        if delta is None:
            self.view.set_zoom_level(1.0)
        else:
            self.view.set_zoom_level(max(0.5, min(3.0, self.view.get_zoom_level() + delta)))

    def _load_changed(self, view, event):
        self.progress.set_visible(event != WebKit.LoadEvent.FINISHED)
        if event == WebKit.LoadEvent.COMMITTED and not self._failed:
            self.offline.set_visible(False)

    def _load_failed(self, view, event, failing_uri, error):
        if error.matches(WebKit.NetworkError.quark(), WebKit.NetworkError.CANCELLED):
            return False
        if event == WebKit.LoadEvent.STARTED or not view.get_uri() or view.get_uri() == failing_uri:
            self._failed = True
            self.offline.set_description(f"{error.message}\n\nCheck your internet connection and try again. "
                                         "Your drive and sync folder keep working from the menu.")
            self.offline.set_visible(True)
            self.progress.set_visible(False)
            return True
        return False

    def _decide_policy(self, view, decision, decision_type):
        if decision_type == WebKit.PolicyDecisionType.NEW_WINDOW_ACTION:
            open_externally(decision.get_navigation_action().get_request().get_uri(), self.get_root())
            decision.ignore()
            return True
        if decision_type == WebKit.PolicyDecisionType.RESPONSE:
            if not decision.is_mime_type_supported():
                decision.download()
                return True
        return False

    def _create(self, view, navigation_action):
        open_externally(navigation_action.get_request().get_uri(), self.get_root())
        return None

    # --- downloads -------------------------------------------------------

    def _download_started(self, session, download):
        download.connect("decide-destination", self._decide_destination)
        download.connect("finished", self._download_finished)
        download.connect("failed", self._download_failed)

    def _decide_destination(self, download, suggested_name):
        path = unique_path(downloads_dir(), suggested_name)
        download.set_destination(str(path))
        return True

    def _download_finished(self, download):
        dest = download.get_destination()
        if dest and self.on_download:
            self.on_download(Path(dest))

    def _download_failed(self, download, error):
        if error.matches(WebKit.DownloadError.quark(), WebKit.DownloadError.CANCELLED_BY_USER):
            return
        if self.on_download_failed:
            self.on_download_failed(error.message)
