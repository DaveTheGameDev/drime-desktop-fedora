# Fallback when python3-devel is not installed (local --nodeps builds).
%{!?python3_sitelib: %global python3_sitelib %(python3 -c "import sysconfig as s; print(s.get_path('purelib', 'rpm_prefix' if 'rpm_prefix' in s.get_scheme_names() else None))")}

Name:           drime-desktop
Version:        0.2.0
Release:        1%{?dist}
Summary:        Unofficial Drime cloud desktop integration (virtual drive, sync folder, web app)
License:        MIT
URL:            https://github.com/DaveTheGameDev/drime-desktop-fedora
Source0:        %{url}/releases/download/v%{version}/%{name}-%{version}.tar.gz
BuildArch:      noarch

BuildRequires:  python3-devel
BuildRequires:  systemd-rpm-macros
BuildRequires:  desktop-file-utils
BuildRequires:  libappstream-glib

Requires:       python3-gobject
Requires:       gtk4
Requires:       libadwaita
Requires:       rclone >= 1.73
Requires:       fuse3
Requires:       hicolor-icon-theme
Recommends:     flatpak
Recommends:     gnome-software
Recommends:     python3-rpm

%description
Recreates the Drime desktop experience on Linux using the native Drime rclone
backend: a virtual drive mounted at ~/Drime, a two-way synced ~/DrimeSync
folder, and the Drime web app in its own window. Includes a graphical setup
and management app. Unofficial project, not affiliated with Drime.

%prep
%autosetup -n %{name}-%{version}

%build
# Nothing to build.

%install
install -d %{buildroot}%{python3_sitelib}/drime_desktop
install -m 0644 src/drime_desktop/*.py %{buildroot}%{python3_sitelib}/drime_desktop/
sed -i 's/@VERSION@/%{version}/' %{buildroot}%{python3_sitelib}/drime_desktop/__init__.py
install -D -m 0755 bin/drime-desktop %{buildroot}%{_bindir}/drime-desktop
install -D -m 0644 systemd/rclone-drime-mount.service %{buildroot}%{_userunitdir}/rclone-drime-mount.service
install -D -m 0644 systemd/drime-bisync.service       %{buildroot}%{_userunitdir}/drime-bisync.service
install -D -m 0644 systemd/drime-bisync.timer         %{buildroot}%{_userunitdir}/drime-bisync.timer
install -D -m 0644 desktop/drime-desktop.desktop %{buildroot}%{_datadir}/applications/drime-desktop.desktop
install -D -m 0644 desktop/drime-webapp.desktop  %{buildroot}%{_datadir}/applications/drime-webapp.desktop
install -D -m 0644 assets/drime.png %{buildroot}%{_datadir}/icons/hicolor/512x512/apps/drime-desktop.png
install -D -m 0644 assets/io.github.davethegamedev.DrimeDesktop.metainfo.xml \
    %{buildroot}%{_metainfodir}/io.github.davethegamedev.DrimeDesktop.metainfo.xml

%check
desktop-file-validate %{buildroot}%{_datadir}/applications/*.desktop
appstream-util validate-relax --nonet %{buildroot}%{_metainfodir}/*.xml

%files
%license LICENSE
%doc README.md
%{_bindir}/drime-desktop
%{python3_sitelib}/drime_desktop/
%{_userunitdir}/rclone-drime-mount.service
%{_userunitdir}/drime-bisync.service
%{_userunitdir}/drime-bisync.timer
%{_datadir}/applications/drime-desktop.desktop
%{_datadir}/applications/drime-webapp.desktop
%{_datadir}/icons/hicolor/512x512/apps/drime-desktop.png
%{_metainfodir}/io.github.davethegamedev.DrimeDesktop.metainfo.xml

%changelog
* Fri Aug 28 2026 DaveTheGameDev - 0.2.0-1
- First RPM release: GTK4/libadwaita setup app, packaged systemd user units,
  self-update via GitHub Releases.
