#!/bin/sh
# PJA110 baseline, phase 4: install the final device package and remove the
# leftover apk wants-symlink copy.  Run as root; no reboot is required for this
# package-only step, but a normal reboot keeps the acceptance boot count honest.
#
#   sudo -i
#   sh /home/penguin/pja110-install/phase4-finalize.sh
set -eu
D=/home/penguin/pja110-install
LOG=$D/phase4-$(date +%Y%m%d-%H%M%S).log
exec 3>&1 4>&2
exec >>"$LOG" 2>&1
say() { printf '%s\n' "$*"; }
fail() {
    say "FAIL: $*"
    chmod 644 "$LOG" 2>/dev/null || true
    { printf '\nPHASE4_FAILED: %s\nfull log: %s\n' "$*" "$LOG"; tail -n 30 "$LOG"; } >&3
    exit 1
}

say "PJA110 baseline phase 4  $(date -Is)"
[ "$(id -u)" = 0 ] || fail "run as root (sudo -i)"

# Pick the newest uploaded device package; never hardcode a pkgrel here.
apk_file=$(ls "$D"/device-oneplus-xigua-1-r*.apk 2>/dev/null | sort -V | tail -n 1)
[ -n "$apk_file" ] || fail "no device-oneplus-xigua APK in $D"
say "installing $apk_file"

say "== install device package =="
apk add --allow-untrusted --force-overwrite "$apk_file" || fail "device package install failed"
installed=$(apk --no-network info -v 2>/dev/null | grep -E '^device-oneplus-xigua-1-r' | head -n 1)
say "installed: $installed"
[ -n "$installed" ] || fail "device package is not installed"

say "== remove apk wants-symlink leftovers =="
for stale in /etc/systemd/system/*.wants/*.apk-new; do
    [ -e "$stale" ] || [ -L "$stale" ] || continue
    case "$stale" in
        *pja110-*) rm -f "$stale"; say "removed $stale" ;;
    esac
done
systemctl daemon-reload

say "== packaged check =="
/usr/libexec/pja110-migrate-baseline check || fail "migrate check did not pass"

say "== transaction list =="
/usr/libexec/pja110-migrate-baseline restore --list || true

say "== unit state =="
systemctl is-enabled pja110-boot-success.service
ls -l /etc/systemd/system/graphical.target.wants/pja110-boot-success.service

chmod 644 "$LOG" 2>/dev/null || true
printf '\nPHASE4_OK installed=%s log=%s\n' "$installed" "$LOG" >&3
trap - EXIT
