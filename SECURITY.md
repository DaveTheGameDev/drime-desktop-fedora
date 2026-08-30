# Security policy

## Supported versions

Only the latest release on the [Releases page](https://github.com/DaveTheGameDev/drime-desktop-linux/releases) receives fixes. Update first if you are on an older version.

## Reporting a vulnerability

Please do not open a public issue for security problems. Instead, use GitHub's private reporting:

**[Report a vulnerability](https://github.com/DaveTheGameDev/drime-desktop-linux/security/advisories/new)**

Include the distribution and version, the Drime Desktop version, how it was installed (RPM, DEB, git checkout) and steps to reproduce. You should hear back within a week. Once fixed, the report is published as an advisory and credited to you unless you prefer otherwise.

## Scope

This project is a thin layer over [rclone](https://rclone.org), systemd user units and a WebKitGTK view of app.drime.cloud. Things in scope here:

- how the API token is stored and passed to rclone
- the systemd units, the installer/uninstaller scripts and the packaging
- the embedded web view (URL handling, downloads, drag and drop)
- the update checker and installer

Out of scope (report to the respective project instead):

- the Drime service itself, app.drime.cloud, or your account — contact [Drime support](https://drime.cloud)
- bugs in rclone, WebKitGTK, GTK or your distribution's packages

## Notes for users

- The API token is stored in rclone's config file (`~/.config/rclone/rclone.conf`) with user-only permissions. Anyone with access to your user account can use it; revoke it at app.drime.cloud → Settings → Developer if a machine is lost or shared.
- The virtual drive keeps a local cache of the files you open under `~/.cache/rclone`. Uninstalling removes it.
