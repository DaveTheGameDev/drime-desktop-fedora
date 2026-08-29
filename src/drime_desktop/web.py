"""The embedded Drime web app (WebKitGTK 6 / GTK4).

DrimeWebView wraps a WebKit.WebView with: persistent login (cookies and local
storage under ~/.local/share/drime-desktop), downloads into ~/Downloads,
links that ask for a new window opened in the system browser, an offline
overlay with Retry, zoom shortcuts, drag-and-drop upload of local files, and a
session keeper that stops "CSRF token mismatch" errors in a long-lived window.

Session keeper: Drime's front end sends the CSRF token it received when the
page was loaded (X-CSRF-TOKEN from bootstrapData) with every write request,
while the server session and its token expire after two idle hours. A browser
tab rarely lives that long; a desktop window does, and then every create,
rename or delete fails until the page is reloaded. A user script renews the
token through GET /api/v1/bootstrap-data (which also keeps the session alive)
every 15 minutes and when the window regains focus after a gap, and rewrites
the token header on outgoing requests. Should a request still get a 419, the
token is renewed at once and the user is asked to retry.

Drag and drop: WebKitGTK's own GTK4 drop handling does not reliably deliver
files to the page, so a capture-phase DropTarget on the widget takes file
drops itself. Each file is exposed to the page through a one-shot
drime-drop:// URL (a private, CORS-enabled URI scheme), and a small script
fetches them, builds File objects and dispatches a genuine drop event at the
drop position, which the Drime web app handles like a browser drop.
"""
from __future__ import annotations

import json
import secrets
from pathlib import Path
from typing import Callable
from urllib.parse import quote, urlparse

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("WebKit", "6.0")
gi.require_version("Soup", "3.0")
from gi.repository import Adw, Gdk, Gio, GLib, GObject, Gtk, Soup, WebKit  # noqa: E402

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


# --- drag-and-drop upload ----------------------------------------------------

DROP_SCHEME = "drime-drop"
_dropped: dict[str, Path] = {}  # token -> file, consumed by the scheme handler
_scheme_registered = False

DROP_JS = """
const files = await Promise.all(JSON.parse(items).map(async i => {
    const r = await fetch(i.url);
    if (!r.ok) throw new Error(`fetch ${i.name}: HTTP ${r.status}`);
    return new File([await r.blob()], i.name, {type: i.type, lastModified: i.mtime});
}));
const dt = new DataTransfer();
files.forEach(f => dt.items.add(f));
const el = document.elementFromPoint(x, y) || document.body;
const ev = t => new DragEvent(t, {bubbles: true, cancelable: true, composed: true,
                                  dataTransfer: dt, clientX: x, clientY: y});
el.dispatchEvent(ev("dragenter"));
el.dispatchEvent(ev("dragover"));
return el.dispatchEvent(ev("drop")) ? "unhandled" : "handled";
"""


def mime_type(path: Path) -> str:
    ctype, _uncertain = Gio.content_type_guess(path.name, None)
    return Gio.content_type_get_mime_type(ctype) or "application/octet-stream"


def _serve_dropped(request: WebKit.URISchemeRequest, *_args) -> None:
    """drime-drop://<token>/<name> -> the local file registered for <token>."""
    path = _dropped.pop(urlparse(request.get_uri()).netloc, None)
    if path is None:
        request.finish_error(GLib.Error("Unknown or already served dropped file"))
        return
    try:
        stream = Gio.File.new_for_path(str(path)).read(None)
        size = path.stat().st_size
    except (GLib.Error, OSError) as e:
        request.finish_error(GLib.Error(str(e)))
        return
    resp = WebKit.URISchemeResponse.new(stream, size)
    resp.set_status(200, "OK")
    resp.set_content_type(mime_type(path))
    headers = Soup.MessageHeaders.new(Soup.MessageHeadersType.RESPONSE)
    headers.append("Access-Control-Allow-Origin", "*")
    resp.set_http_headers(headers)
    request.finish_with_response(resp)


def _register_drop_scheme() -> None:
    global _scheme_registered
    if _scheme_registered:
        return
    ctx = WebKit.WebContext.get_default()
    ctx.register_uri_scheme(DROP_SCHEME, _serve_dropped, None)
    sec = ctx.get_security_manager()
    sec.register_uri_scheme_as_secure(DROP_SCHEME)
    sec.register_uri_scheme_as_cors_enabled(DROP_SCHEME)
    _scheme_registered = True


# --- session keeper ------------------------------------------------------------

SESSION_HANDLER = "drimeSession"

SESSION_JS = """
(() => {
    const REFRESH_MS = 15 * 60 * 1000, FOCUS_MS = 5 * 60 * 1000;
    let token = null, last = Date.now(), pending = null;
    const tell = msg => { try { window.webkit.messageHandlers.%(handler)s.postMessage(msg); } catch (e) {} };

    const setHeader = XMLHttpRequest.prototype.setRequestHeader;
    XMLHttpRequest.prototype.setRequestHeader = function (name, value) {
        if (token && /^x-csrf-token$/i.test(name)) value = token;
        return setHeader.call(this, name, value);
    };
    const send = XMLHttpRequest.prototype.send;
    XMLHttpRequest.prototype.send = function (...args) {
        this.addEventListener("loadend", () => {
            if (this.status === 419) refresh().then(ok => tell(ok ? "expired" : "expired-unrecoverable"));
        });
        return send.apply(this, args);
    };

    function refresh() {
        if (pending) return pending;
        pending = (async () => {
            try {
                const r = await fetch("/api/v1/bootstrap-data", {credentials: "include", cache: "no-store",
                                                                 headers: {Accept: "application/json"}});
                if (!r.ok) return false;
                const data = (await r.json()).data;
                const t = (typeof data === "string" ? JSON.parse(atob(data)) : data).csrf_token;
                if (typeof t !== "string" || !t) return false;
                token = t;
                last = Date.now();
                return true;
            } catch (e) {
                return false;
            } finally {
                pending = null;
            }
        })();
        return pending;
    }
    setInterval(() => { if (Date.now() - last > REFRESH_MS) refresh(); }, 60 * 1000);
    window.addEventListener("focus", () => { if (Date.now() - last > FOCUS_MS) refresh(); });
})();
""" % {"handler": SESSION_HANDLER}


def _session_keeper() -> WebKit.UserContentManager:
    ucm = WebKit.UserContentManager()
    ucm.register_script_message_handler(SESSION_HANDLER, None)
    ucm.add_script(WebKit.UserScript.new(SESSION_JS, WebKit.UserContentInjectedFrames.TOP_FRAME,
                                         WebKit.UserScriptInjectionTime.START, [backend.WEB_URL + "/*"], None))
    return ucm


class DrimeWebView(Gtk.Overlay):
    """WebView + offline overlay. `on_download(path)` is called when a file was saved,
    `on_notice(text)` with short messages for the user (e.g. about dropped folders)."""

    def __init__(self, on_download: Callable[[Path], None] | None = None,
                 on_download_failed: Callable[[str], None] | None = None,
                 on_notice: Callable[[str], None] | None = None):
        super().__init__()
        self.on_download = on_download
        self.on_download_failed = on_download_failed
        self.on_notice = on_notice
        _register_drop_scheme()

        backend.WEB_DATA_DIR.mkdir(parents=True, exist_ok=True)
        backend.WEB_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        self.session = WebKit.NetworkSession.new(str(backend.WEB_DATA_DIR), str(backend.WEB_CACHE_DIR))
        cookies = self.session.get_cookie_manager()
        cookies.set_persistent_storage(str(backend.WEB_DATA_DIR / "cookies.sqlite"),
                                       WebKit.CookiePersistentStorage.SQLITE)
        cookies.set_accept_policy(WebKit.CookieAcceptPolicy.NO_THIRD_PARTY)
        self.session.connect("download-started", self._download_started)

        self.ucm = _session_keeper()
        self.ucm.connect(f"script-message-received::{SESSION_HANDLER}", self._session_message)
        self.view = WebKit.WebView(network_session=self.session, user_content_manager=self.ucm,
                                   hexpand=True, vexpand=True)
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

        drop = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY)
        drop.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)  # before WebKit's own target
        drop.connect("drop", self._drop_files)
        self.add_controller(drop)

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

    # --- drag and drop -----------------------------------------------------

    def notice(self, text: str) -> None:
        if self.on_notice:
            self.on_notice(text)

    def _drop_files(self, target, value: Gdk.FileList, x: float, y: float) -> bool:
        paths = [Path(f.get_path()) for f in value.get_files() if f.get_path()]
        return self.drop_paths(paths, x, y)

    def drop_paths(self, paths: list[Path], x: float, y: float) -> bool:
        """Hand local files to the web app as a drop at widget coordinates (x, y)."""
        files = [p for p in paths if p.is_file()]
        if any(p.is_dir() for p in paths):
            self.notice(f"Folders can't be dropped here — copy them into {backend.MOUNT} instead.")
        if not files:
            return bool(paths)
        items = []
        for p in files:
            token = secrets.token_urlsafe(16)
            _dropped[token] = p
            items.append({"url": f"{DROP_SCHEME}://{token}/{quote(p.name)}", "name": p.name,
                          "type": mime_type(p), "mtime": int(p.stat().st_mtime * 1000)})
        zoom = self.view.get_zoom_level() or 1.0
        args = GLib.Variant("a{sv}", {"items": GLib.Variant("s", json.dumps(items)),
                                      "x": GLib.Variant("d", x / zoom), "y": GLib.Variant("d", y / zoom)})
        self.view.call_async_javascript_function(DROP_JS, -1, args, None, None, None, self._drop_done, len(files))
        return True

    def _drop_done(self, view, result, count: int):
        try:
            value = view.call_async_javascript_function_finish(result)
        except GLib.Error as e:
            self.notice(f"Couldn't hand the dropped files to Drime: {e.message}")
            return
        if value.to_string() != "handled":
            self.notice("Drime didn't accept the drop here — open the folder you want to upload to and try again.")

    # --- session keeper ----------------------------------------------------

    def _session_message(self, manager, value):
        msg = value.to_string()
        if msg == "expired":
            self.notice("Your Drime session had expired and was renewed — please try that again.")
        elif msg == "expired-unrecoverable":
            self.notice("Your Drime session has expired — reload the page (Ctrl+R) and sign in again if asked.")

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
