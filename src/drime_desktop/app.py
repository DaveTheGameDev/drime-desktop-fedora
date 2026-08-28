"""GTK4 / libadwaita application: status, updates, removal."""
from __future__ import annotations

import threading
import time
from typing import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from . import APP_ID, __version__, backend, updates  # noqa: E402


def run_async(fn: Callable, on_done: Callable[[object, Exception | None], None]) -> None:
    """Run fn() in a thread; call on_done(result, error) on the main loop."""
    def worker():
        try:
            result, err = fn(), None
        except Exception as e:  # noqa: BLE001
            result, err = None, e
        GLib.idle_add(on_done, result, err)
    threading.Thread(target=worker, daemon=True).start()


def relative_time(ts: int | None) -> str:
    if not ts:
        return "never"
    d = int(ts - time.time())
    ago = d < 0
    d = abs(d)
    if d < 60:
        s = "less than a minute"
    elif d < 3600:
        s = f"{d // 60} min"
    elif d < 86400:
        s = f"{d // 3600} h {d % 3600 // 60} min"
    else:
        s = f"{d // 86400} days"
    return f"{s} ago" if ago else f"in {s}"


def button(label: str, cb: Callable, *css: str) -> Gtk.Button:
    b = Gtk.Button(label=label, valign=Gtk.Align.CENTER)
    for c in css:
        b.add_css_class(c)
    b.connect("clicked", lambda _b: cb())
    return b


class LogView(Gtk.ScrolledWindow):
    """Monospace log box fed from worker threads via append()."""

    def __init__(self, height: int = 180):
        super().__init__(min_content_height=height, max_content_height=height,
                         propagate_natural_height=True)
        self.view = Gtk.TextView(editable=False, monospace=True, cursor_visible=False,
                                 left_margin=8, right_margin=8, top_margin=6, bottom_margin=6,
                                 wrap_mode=Gtk.WrapMode.WORD_CHAR)
        self.add_css_class("card")
        self.set_child(self.view)

    def append(self, line: str) -> None:
        def do():
            buf = self.view.get_buffer()
            buf.insert(buf.get_end_iter(), line + "\n")
            self.view.scroll_to_mark(buf.get_insert(), 0, False, 0, 0)
        GLib.idle_add(do)

    def set_text(self, text: str) -> None:
        self.view.get_buffer().set_text(text)


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application, notice: str | None = None):
        super().__init__(application=app, title="Drime", default_width=640, default_height=720)
        self._refreshing = False
        self._known: backend.State | None = None   # last state read from the system
        self._release: updates.Release | None = None
        self.browser: backend.Browser | None = None

        self.toasts = Adw.ToastOverlay()
        view = Adw.ToolbarView()
        view.add_top_bar(Adw.HeaderBar())
        self.nav = Adw.NavigationView()
        view.set_content(self.nav)
        self.toasts.set_child(view)
        self.set_content(self.toasts)

        self.page = Adw.PreferencesPage()
        self.nav.add(Adw.NavigationPage.new(self.page, "Drime"))
        self._build_status()
        self._build_updates()
        self._build_remove()

        self.refresh()
        GLib.timeout_add_seconds(10, self._tick)
        if notice:
            self.toast(notice)
        self._startup_migration()

    # --- building ----------------------------------------------------------

    def _build_status(self):
        g = Adw.PreferencesGroup(title="Status")
        self.page.add(g)

        self.drive_row = Adw.SwitchRow(title="Virtual drive", subtitle=str(backend.MOUNT))
        self.drive_row.add_prefix(Gtk.Image.new_from_icon_name("drive-harddisk-symbolic"))
        self.drive_row.add_suffix(button("Open folder", self.open_folder))
        self.drive_row.connect("notify::active", self._on_drive_switch)
        g.add(self.drive_row)

        self.sync_row = Adw.SwitchRow(title="Sync folder", subtitle=str(backend.SYNC_DIR))
        self.sync_row.add_prefix(Gtk.Image.new_from_icon_name("folder-remote-symbolic"))
        self.sync_row.add_suffix(button("Sync now", self.sync_now))
        self.sync_row.connect("notify::active", self._on_sync_switch)
        g.add(self.sync_row)

        self.log_row = Adw.ExpanderRow(title="Sync log")
        self.sync_log = LogView()
        self.log_row.add_row(self.sync_log)
        self.log_row.connect("notify::expanded", lambda *_: self._load_sync_log())
        g.add(self.log_row)

        self.web_row = Adw.ActionRow(title="Web app", subtitle="app.drime.cloud")
        self.web_row.add_prefix(Gtk.Image.new_from_icon_name("network-server-symbolic"))
        self.web_open_btn = button("Open", self.open_web)
        self.web_install_btn = button("Install Chromium", self.install_browser, "suggested-action")
        self.web_row.add_suffix(self.web_install_btn)
        self.web_row.add_suffix(self.web_open_btn)
        g.add(self.web_row)

    def _build_updates(self):
        g = Adw.PreferencesGroup(title="Updates")
        self.page.add(g)

        self.update_row = Adw.ActionRow(title="Drime Desktop", subtitle=f"Version {__version__}")
        self.update_row.add_prefix(Gtk.Image.new_from_icon_name("view-refresh-symbolic"))
        self.update_check_btn = button("Check for updates", self.check_updates)
        self.update_install_btn = button("Download and install", self.download_update, "suggested-action")
        self.update_install_btn.set_visible(False)
        self.update_spinner = Gtk.Spinner(valign=Gtk.Align.CENTER)
        self.update_row.add_suffix(self.update_spinner)
        self.update_row.add_suffix(self.update_install_btn)
        self.update_row.add_suffix(self.update_check_btn)
        g.add(self.update_row)

        self.browser_row = Adw.ActionRow(title="Browser for the web app")
        self.browser_row.add_prefix(Gtk.Image.new_from_icon_name("preferences-system-symbolic"))
        self.browser_update_btn = button("Update", self.update_browser)
        self.browser_software_btn = button("Open in Software", self.browser_in_software)
        self.browser_spinner = Gtk.Spinner(valign=Gtk.Align.CENTER)
        self.browser_row.add_suffix(self.browser_spinner)
        self.browser_row.add_suffix(self.browser_software_btn)
        self.browser_row.add_suffix(self.browser_update_btn)
        g.add(self.browser_row)

    def _build_remove(self):
        g = Adw.PreferencesGroup(title="Remove")
        self.page.add(g)
        row = Adw.ActionRow(title="Remove my setup",
                            subtitle="Unmounts the drive, stops syncing and removes the launcher. "
                                     f"{backend.SYNC_DIR.name} and your cloud data are kept.")
        row.add_prefix(Gtk.Image.new_from_icon_name("user-trash-symbolic"))
        row.add_suffix(button("Remove…", self.confirm_remove, "destructive-action"))
        g.add(row)

    # --- state -------------------------------------------------------------

    def toast(self, text: str) -> None:
        self.toasts.add_toast(Adw.Toast.new(text))

    def _tick(self) -> bool:
        self.refresh()
        return True

    def refresh(self) -> None:
        def done(result, err):
            if err or result is None:
                return
            st, ss = result
            self._refreshing = True
            try:
                self._known = st
                if self.drive_row.get_active() != st.mount_enabled:
                    self.drive_row.set_active(st.mount_enabled)
                self.drive_row.set_subtitle(
                    f"{backend.MOUNT} — " + ("mounted" if st.mounted else
                                            "starting…" if st.mount_active else
                                            "enabled, not mounted" if st.mount_enabled else "off"))
                if self.sync_row.get_active() != st.sync_enabled:
                    self.sync_row.set_active(st.sync_enabled)
                if ss.running:
                    sub = "syncing now…"
                elif not st.sync_enabled:
                    sub = "off"
                else:
                    last = "never synced" if not ss.last_end else \
                        f"last sync {relative_time(ss.last_end)} ({'ok' if ss.last_result == 'success' else 'failed'})"
                    sub = last + (f", next {relative_time(ss.next_run)}" if ss.next_run else "")
                self.sync_row.set_subtitle(f"{backend.SYNC_DIR} ↔ {backend.SYNC_REMOTE_PATH} — {sub}")
                self.web_row.set_subtitle(f"Opens in {st.browser.name}" if st.browser
                                          else "No Chromium-based browser found")
                self.web_open_btn.set_visible(st.browser is not None)
                self.web_install_btn.set_visible(st.browser is None)
                self.browser_row.set_subtitle(
                    f"{st.browser.name}" + (f" — {st.browser.flatpak_id}" if st.browser and st.browser.flatpak_id else "")
                    if st.browser else "None installed")
                is_fp = bool(st.browser and st.browser.flatpak_id)
                self.browser_update_btn.set_visible(is_fp)
                self.browser_software_btn.set_visible(is_fp)
                self.browser = st.browser
            finally:
                self._refreshing = False
        run_async(lambda: (backend.state(), backend.sync_status()), done)

    def _startup_migration(self):
        def done(result, _err):
            if result:
                self.toast("Switched to the packaged systemd units")
        def work():
            migrated = backend.migrate_user_units()
            backend.cleanup_legacy()
            return migrated
        run_async(work, done)

    # --- actions -----------------------------------------------------------

    def _user_toggled(self, row, known_value: bool) -> bool:
        """True only for a real user toggle: state is known, we are not refreshing,
        and the switch now differs from what the system reports."""
        return (not self._refreshing and self._known is not None
                and row.get_active() != known_value)

    def _on_drive_switch(self, row, _pspec):
        if not self._user_toggled(row, self._known.mount_enabled if self._known else False):
            return
        self._known.mount_enabled = row.get_active()
        fn = backend.mount_enable if row.get_active() else backend.mount_disable
        def done(_r, err):
            if err:
                self.toast(f"Error: {err}")
            self.refresh()
        def work():
            fn()
            if row.get_active():
                backend.bookmark_add()
                backend.folder_icon_set()
        run_async(work, done)

    def _on_sync_switch(self, row, _pspec):
        if not self._user_toggled(row, self._known.sync_enabled if self._known else False):
            return
        self._known.sync_enabled = row.get_active()
        fn = backend.sync_enable if row.get_active() else backend.sync_disable
        def done(_r, err):
            if err:
                self.toast(f"Error: {err}")
            self.refresh()
        run_async(fn, done)

    def open_folder(self):
        Gio.AppInfo.launch_default_for_uri(f"file://{backend.MOUNT}", None)

    def sync_now(self):
        backend.sync_now()
        self.toast("Sync started")
        GLib.timeout_add_seconds(2, lambda: (self.refresh(), False)[1])

    def _load_sync_log(self):
        if self.log_row.get_expanded():
            run_async(backend.sync_log_tail, lambda text, _e: self.sync_log.set_text(text or ""))

    def open_web(self):
        if self.browser:
            backend.open_web_app(self.browser)

    def install_browser(self):
        self.web_install_btn.set_sensitive(False)
        self.toast("Installing Chromium from Flathub… this can take a few minutes")
        log = LogView()
        self.log_row.set_expanded(True)
        def done(ok, err):
            self.web_install_btn.set_sensitive(True)
            self.toast("Chromium installed" if ok and not err else f"Installation failed: {err or 'see log'}")
            self.refresh()
        run_async(lambda: backend.install_chromium_flatpak(self.sync_log.append), done)

    def check_updates(self):
        self.update_check_btn.set_sensitive(False)
        self.update_spinner.start()
        def done(rel, err):
            self.update_spinner.stop()
            self.update_check_btn.set_sensitive(True)
            if err:
                self.update_row.set_subtitle(f"Version {__version__} — {err}")
                return
            if rel is None:
                self.update_row.set_subtitle(f"Version {__version__} — no releases published yet")
                return
            if updates.is_newer(rel.version, __version__):
                self._release = rel
                self.update_row.set_subtitle(f"Version {__version__} — version {rel.version} is available")
                self.update_install_btn.set_visible(rel.rpm_url is not None)
                if rel.rpm_url is None:
                    updates.open_releases_page()
            else:
                self.update_row.set_subtitle(f"Version {__version__} — up to date")
        run_async(updates.fetch_latest, done)

    def download_update(self):
        rel = self._release
        if not rel or not rel.rpm_url:
            return
        self.update_install_btn.set_sensitive(False)
        self.update_spinner.start()
        def progress(done_b, total):
            pct = f" {done_b * 100 // total}%" if total else ""
            GLib.idle_add(self.update_row.set_subtitle, f"Downloading {rel.version}…{pct}")
        def done(path, err):
            self.update_spinner.stop()
            self.update_install_btn.set_sensitive(True)
            if err:
                self.toast(str(err))
                return
            updates.open_for_install(path)
            self.update_row.set_subtitle(f"Downloaded to {path.parent} — finish the update in Software")
        run_async(lambda: updates.download_rpm(rel.rpm_url, progress), done)

    def update_browser(self):
        if not self.browser:
            return
        self.browser_update_btn.set_sensitive(False)
        self.browser_spinner.start()
        self.log_row.set_expanded(True)
        def done(ok, err):
            self.browser_spinner.stop()
            self.browser_update_btn.set_sensitive(True)
            self.toast("Browser is up to date" if ok and not err else f"Browser update failed: {err or 'see log'}")
        run_async(lambda: backend.update_browser_flatpak(self.browser, self.sync_log.append), done)

    def browser_in_software(self):
        if self.browser and self.browser.flatpak_id and not backend.open_in_software(self.browser.flatpak_id):
            self.toast("GNOME Software is not installed")

    def confirm_remove(self):
        dlg = Adw.AlertDialog.new("Remove your Drime setup?",
                                  "The virtual drive will be unmounted and syncing stopped. "
                                  f"{backend.SYNC_DIR} and everything in your cloud account are kept.")
        purge = Gtk.CheckButton(label="Also delete the API token (rclone remote)")
        dlg.set_extra_child(purge)
        dlg.add_response("cancel", "Cancel")
        dlg.add_response("remove", "Remove")
        dlg.set_response_appearance("remove", Adw.ResponseAppearance.DESTRUCTIVE)
        dlg.set_default_response("cancel")
        dlg.connect("response", lambda _d, r: r == "remove" and self._do_remove(purge.get_active()))
        dlg.present(self)

    def _do_remove(self, purge: bool):
        status = Adw.StatusPage(title="Removing…", icon_name="user-trash-symbolic")
        log = LogView(220)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_start=24, margin_end=24)
        box.append(log)
        status.set_child(box)
        page = Adw.NavigationPage.new(status, "Remove")
        page.set_can_pop(False)
        self.nav.push(page)

        def done(_r, err):
            if err:
                status.set_title("Something went wrong")
                status.set_description(str(err))
                page.set_can_pop(True)
                return
            status.set_title("Drime setup removed")
            status.set_description(
                f"{backend.SYNC_DIR} and your cloud data were kept. "
                "To remove this app as well, uninstall “Drime” in GNOME Software "
                "or run: sudo dnf remove drime-desktop")
            box.append(button("Close", self.close, "pill"))
        run_async(lambda: backend.uninstall_all(purge, log.append), done)


class DrimeApp(Adw.Application):
    def __init__(self, notice: str | None = None):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.notice = notice

    def do_activate(self):
        win = self.get_active_window()
        if win is None:
            from .wizard import needs_wizard, WizardWindow
            if needs_wizard():
                win = WizardWindow(self, on_finished=self.show_main)
            else:
                win = MainWindow(self, self.notice)
        win.present()

    def show_main(self, wizard: Gtk.Window):
        wizard.close()
        MainWindow(self).present()


def run_gui(notice: str | None = None) -> int:
    return DrimeApp(notice).run(None)
