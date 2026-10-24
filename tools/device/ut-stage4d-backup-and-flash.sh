#!/bin/sh
# Stage 4d: back up everything needed to return to the current system (including
# the modem/IMEI partitions), then optionally flash the UT boot image.
#
# Backups go to /var/lib/ut-root/backup-<timestamp>/ and are also copied to
# /home/penguin/ut-backup/ so they survive a root filesystem change.
#
# Partitions backed up:
#   boot_a                      current pmOS boot image (rollback)
#   modem_a, modem_b            modem firmware
#   fsg, fsc                    modem storage (fsg holds IMEI-related data)
#   modemst1, modemst2          modem persistent storage (IMEI backup)
#   persist                     calibration / device specific data
#   ocdt, oplusstanvbk_a        device tree / standby calibration
#
#   sudo -i
#   sh /home/penguin/ut-test/ut-stage4d-backup-and-flash.sh backup
#   sh /home/penguin/ut-test/ut-stage4d-backup-and-flash.sh flash
#
# Default action is "backup": it only reads partitions and writes files.
set -eu
OUT=${OUT:-/home/penguin/ut-test}
IMG=${IMG:-$OUT/boot_a-ut-super.img}
DEV_BOOT=/dev/disk/by-partlabel/boot_a
MODE=${1:-backup}
TS=$(date +%Y%m%d-%H%M%S)
DEST=/var/lib/ut-root/backup-$TS
SAFE=/home/penguin/ut-backup
LOG=$OUT/ut-stage4d-$TS.log
mkdir -p "$OUT"
exec 3>&1 4>&2
exec >>"$LOG" 2>&1
say() { printf '%s\n' "$*"; }
fail() {
    say "FAIL: $*"
    chmod 644 "$LOG" 2>/dev/null || true
    { printf '\nUT_STAGE4D_FAILED: %s\nlog: %s\n' "$*" "$LOG"; tail -n 40 "$LOG"; } >&3
    exit 1
}

[ "$(id -u)" = 0 ] || fail "run as root (sudo -i)"

case "$MODE" in
backup)
    say "== backup to $DEST =="
    mkdir -p "$DEST"
    PARTITIONS="boot_a modem_a modem_b fsg fsc modemst1 modemst2 persist ocdt oplusstanvbk_a"
    : > "$DEST/SHA256SUMS"
    for p in $PARTITIONS; do
        src=/dev/disk/by-partlabel/$p
        [ -e "$src" ] || { say "skip $p (absent)"; continue; }
        size=$(cat /sys/class/block/$(basename "$(readlink -f "$src")")/size 2>/dev/null || echo 0)
        [ "$size" -gt 0 ] || { say "skip $p (zero size)"; continue; }
        say "reading $p ($((size * 512 / 1024)) KiB)"
        dd if="$src" of="$DEST/$p.img" bs=1M status=none || fail "dd $p failed"
        ( cd "$DEST" && sha256sum "$p.img" >> SHA256SUMS )
    done
    sync
    say "backup files:"
    ls -lh "$DEST" | tail -15
    say "== copy to $SAFE (survives root changes) =="
    mkdir -p "$SAFE"
    cp -a "$DEST" "$SAFE/" || say "WARN: copy to $SAFE failed"
    say "copied to $SAFE/$(basename "$DEST")"
    say "total size: $(du -sh "$DEST" | cut -f1)"
    say ""
    say "rollback command (restore everything):"
    say "  for p in $PARTITIONS; do [ -f $DEST/\$p.img ] && dd if=$DEST/\$p.img of=/dev/disk/by-partlabel/\$p bs=1M conv=fsync; done"
    printf '\nUT_BACKUP_DONE dest=%s log=%s\n' "$DEST" "$LOG" >&3
    ;;
flash)
    say "== flashing UT boot image =="
    [ -f "$IMG" ] || fail "missing $IMG"
    [ -b "$DEV_BOOT" ] || fail "missing $DEV_BOOT"
    say "boot_a before: $(sha256sum "$DEV_BOOT" | cut -d' ' -f1)"
    say "image: $(sha256sum "$IMG" | cut -d' ' -f1)"
    say "refusing to continue unless the backup exists"
    ls -d /var/lib/ut-root/backup-* >/dev/null 2>&1 || fail "no backup found; run 'backup' first"
    dd if="$IMG" of="$DEV_BOOT" bs=1M conv=fsync status=none || fail "dd failed"
    sync
    after=$(sha256sum "$DEV_BOOT" | cut -d' ' -f1)
    say "boot_a after:  $after"
    [ "$after" = "$(sha256sum "$IMG" | cut -d' ' -f1)" ] || fail "read-back mismatch"
    say ""
    say "boot_a now points at the UT root on /dev/sda6."
    say "next: reboot and watch the screen; SSH will not work until userspace is up."
    say "rollback: dd if=<backup>/boot_a.img of=/dev/disk/by-partlabel/boot_a bs=1M conv=fsync"
    printf '\nUT_FLASH_DONE log=%s\n' "$LOG" >&3
    ;;
*)
    fail "usage: $0 backup|flash"
    ;;
esac
