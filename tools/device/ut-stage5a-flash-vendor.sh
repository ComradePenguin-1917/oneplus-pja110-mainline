#!/bin/sh
# Stage 5a: flash the no-initramfs vendor_boot so the kernel mounts root=UUID itself.
#
# Why vendor_boot: the kernel needs an empty (or absent) userspace initramfs to
# jump straight to root=UUID=<ut-root>. fastboot boot only accepts a boot image,
# so the vendor fragment has to be written to the partition once.
#
# Safety: vendor_boot_a is backed up first; boot_a is left untouched, so the
# pmOS kernel and its own vendor ramdisk can be restored independently.
#
#   sudo -i
#   sh /home/penguin/ut-test/ut-stage5a-flash-vendor.sh backup
#   sh /home/penguin/ut-test/ut-stage5a-flash-vendor.sh flash
set -eu
OUT=${OUT:-/home/penguin/ut-test}
VENDOR=${VENDOR:-$OUT/vendor_boot_a-noinitrd.img}
DEV=/dev/disk/by-partlabel/vendor_boot_a
TS=$(date +%Y%m%d-%H%M%S)
DEST=/var/lib/ut-root/backup-$TS
SAFE=/home/penguin/ut-backup
LOG=$OUT/ut-stage5a-$TS.log
mkdir -p "$OUT"
exec 3>&1 4>&2
exec >>"$LOG" 2>&1
say() { printf '%s\n' "$*"; }
fail() {
    say "FAIL: $*"
    chmod 644 "$LOG" 2>/dev/null || true
    { printf '\nUT_STAGE5A_FAILED: %s\nlog: %s\n' "$*" "$LOG"; tail -n 30 "$LOG"; } >&3
    exit 1
}

[ "$(id -u)" = 0 ] || fail "run as root (sudo -i)"
MODE=${1:-backup}

case "$MODE" in
backup)
    mkdir -p "$DEST"
    say "== backing up vendor_boot_a =="
    dd if="$DEV" of="$DEST/vendor_boot_a.img" bs=1M status=none || fail "backup failed"
    ( cd "$DEST" && sha256sum vendor_boot_a.img > vendor_boot_a.sha256 )
    say "size: $(du -h "$DEST/vendor_boot_a.img" | cut -f1)"
    say "sha256: $(cat "$DEST/vendor_boot_a.sha256")"
    mkdir -p "$SAFE"
    cp -a "$DEST" "$SAFE/" || say "WARN: copy to $SAFE failed"
    say "copied to $SAFE/$(basename "$DEST")"
    say ""
    say "restore command:"
    say "  dd if=$DEST/vendor_boot_a.img of=$DEV bs=1M conv=fsync"
    printf '\nUT_VENDOR_BACKUP_DONE dest=%s log=%s\n' "$DEST" "$LOG" >&3
    ;;
flash)
    [ -f "$VENDOR" ] || fail "missing $VENDOR"
    say "== flashing vendor_boot_a =="
    say "before: $(sha256sum "$DEV" | cut -d' ' -f1)"
    ls -d /var/lib/ut-root/backup-*/vendor_boot_a.img >/dev/null 2>&1 ||
        fail "no vendor_boot_a backup found; run 'backup' first"
    dd if="$VENDOR" of="$DEV" bs=1M conv=fsync status=none || fail "dd failed"
    sync
    after=$(sha256sum "$DEV" | cut -d' ' -f1)
    want=$(sha256sum "$VENDOR" | cut -d' ' -f1)
    say "after:  $after"
    [ "$after" = "$want" ] || fail "read-back mismatch (want $want)"
    say "vendor_boot_a now carries the empty initramfs"
    say "boot_a untouched; fastboot boot the UT boot image to test"
    printf '\nUT_VENDOR_FLASH_DONE log=%s\n' "$LOG" >&3
    ;;
*)
    fail "usage: $0 backup|flash"
    ;;
esac
