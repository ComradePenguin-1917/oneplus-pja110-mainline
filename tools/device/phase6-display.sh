#!/bin/sh
# PJA110 display test: install the r3 kernel and flash the 120 Hz or 60 Hz
# boot_a image.  Run as root, then reboot normally.
#
#   sudo -i
#   sh /home/penguin/pja110-install/display-120/phase6-display.sh 120
#   reboot
#
# If the panel stays black, SSH in and run the same script with "60".
set -eu
MODE=${1:-120}
D=/home/penguin/pja110-install/display-120
APK=$D/linux-oneplus-xigua-6.14-r3.apk
case "$MODE" in
    120) IMG=$D/boot_a-120.img; WANT=ae22af5ff1956960f00c16c9306ee0dce91f0f367b448fdc4a55226c7aad858c ;;
    60)  IMG=$D/boot_a-60.img;  WANT=ef945faef2f6f260f8fd9f16d467ad604836b1639c53336f24121652d2bb116d ;;
    *) echo "usage: $0 120|60" >&2; exit 2 ;;
esac
say() { printf '%s\n' "$*"; }
fail() { say "FAIL: $*"; exit 1; }

[ "$(id -u)" = 0 ] || fail "run as root (sudo -i)"
[ -f "$APK" ] || fail "missing $APK"
[ -f "$IMG" ] || fail "missing $IMG"
for p in boot_a; do test -e /dev/disk/by-partlabel/$p || fail "missing /dev/disk/by-partlabel/$p"; done
say "before: $(sha256sum /dev/disk/by-partlabel/boot_a | cut -d' ' -f1)"

say "== install linux-oneplus-xigua 6.14-r3 =="
apk add --allow-untrusted --force-overwrite "$APK" || fail "kernel package install failed"
apk --no-network info -v 2>/dev/null | grep -q '^linux-oneplus-xigua-6.14-r3' ||
    fail "kernel package is not 6.14-r3"
say "installed: $(apk --no-network info -v 2>/dev/null | grep '^linux-oneplus-xigua')"

say "== flash boot_a ($MODE Hz image) =="
dd if="$IMG" of=/dev/disk/by-partlabel/boot_a bs=1M || fail "boot_a write failed"
sync
got=$(sha256sum /dev/disk/by-partlabel/boot_a | cut -d' ' -f1)
say "after:  $got"
[ "$got" = "$WANT" ] || fail "boot_a read-back mismatch (want $WANT)"
say "PASS: boot_a now carries the $MODE Hz cmdline; reboot normally"
say "If the display stays dark: ssh in and run this script with 60"
