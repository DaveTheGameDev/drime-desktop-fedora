#!/bin/sh
# Print a Debian changelog generated from the spec's %changelog, so the spec
# stays the single source of versions and release notes. Used by `make deb`;
# debian/changelog itself is not committed.
set -e
cd "$(dirname "$0")/.."
maintainer="DaveTheGameDev <300138453+DaveTheGameDev@users.noreply.github.com>"   # must match debian/control
awk -v m="$maintainer" '
  # Items are re-wrapped: the spec indents continuation lines by 2, Debian by 4.
  function wrap(text,   n, i, words, line, out) {
    n = split(text, words, " "); line = "  *"; out = ""
    for (i = 1; i <= n; i++) {
      if (length(line) + 1 + length(words[i]) > 78 && line != "   ") { out = out line "\n"; line = "   " }
      line = line " " words[i]
    }
    return out line
  }
  function flush() { if (item != "") print wrap(item); item = ""
                     if (open) printf "\n -- %s  %s\n\n", m, date; open = 0 }
  /^%changelog/ { on = 1; next }
  !on { next }
  # "* Sun Aug 30 2026 Name - 0.3.11-1"  ->  "drime-desktop (0.3.11) unstable; ..."
  # The spec dates entries by day only; lintian wants each entry newer than the
  # previous one, so same-day entries get distinct, decreasing times.
  /^\* / { flush(); ver = $NF; sub(/-[0-9]+$/, "", ver); s = 86399 - n++
           date = sprintf("%s, %02d %s %s %02d:%02d:%02d +0000", $2, $4, $3, $5, s / 3600, s % 3600 / 60, s % 60)
           printf "drime-desktop (%s) unstable; urgency=medium\n\n", ver; open = 1; next }
  /^- /  { if (item != "") print wrap(item); item = substr($0, 3); next }
  /^  /  { sub(/^ +/, ""); item = item " " $0; next }
  END { flush() }' drime-desktop.spec
