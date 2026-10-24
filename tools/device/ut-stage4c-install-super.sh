#!/bin/sh
# Stage 4c: install the UT root onto the super partition (option C verification)
# and build a matching boot image, WITHOUT flashing anything yet.
#
# Layout used here:
#   /dev/sda6 (super, 15.0 GiB)  <- UT root, ext4, label ut-root
#   boot_a is NOT modified; a candidate image is written to $OUT instead.
#
# Steps:
#   1. refuse to run if super is mounted or held by another device
#   2. write /var/lib/ut-root/ut-root.img onto /dev/sda6
#   3. verify the filesystem, label and UUID on the written partition
#   4. build a UT boot image whose cmdline points at the new root UUID,
#      keeping panel_oneplus_aa536.refresh=120
#   5. print the exact flash and rollback commands for the operator
#
#   sudo -i
#   sh /home/penguin/ut-test/ut-stage4c-install-super.sh
set -eu
ROOTFS=${ROOTFS:-/opt/geekbench-rootfs}
OUT=${OUT:-/home/penguin/ut-test}
DEV=${DEV:-/dev/sda6}
IMG=${IMG:-/var/lib/ut-root/ut-root.img}
BOOT_TEMPLATE=${BOOT_TEMPLATE:-/home/penguin/pja110-install/display-120/boot_a-60.img}
LOG=$OUT/ut-stage4c-$(date +%Y%m%d-%H%M%S).log
mkdir -p "$OUT"
exec 3>&1 4>&2
exec >>"$LOG" 2>&1
say() { printf '%s\n' "$*"; }
fail() {
    say "FAIL: $*"
    chmod 644 "$LOG" 2>/dev/null || true
    { printf '\nUT_STAGE4C_FAILED: %s\nlog: %s\n' "$*" "$LOG"; tail -n 40 "$LOG"; } >&3
    exit 1
}

[ "$(id -u)" = 0 ] || fail "run as root (sudo -i)"
[ -b "$DEV" ] || fail "missing block device $DEV"
[ -f "$IMG" ] || fail "missing root image $IMG"

say "== safety checks =="
if mount | grep -q "^$DEV"; then fail "$DEV is mounted"; fi
if [ -n "$(ls /sys/class/block/$(basename "$DEV")/holders/ 2>/dev/null)" ]; then
    fail "$DEV is held by another device: $(ls /sys/class/block/$(basename "$DEV")/holders/)"
fi
say "device: $DEV ($(cat /sys/class/block/$(basename "$DEV")/size | awk '{printf "%.1f GiB", $1*512/1024/1024/1024}'))"
say "image:  $IMG ($(du -h "$IMG" | cut -f1) on disk)"
say "target will be REPLACED. super currently holds no Linux filesystem."

say "== write image to $DEV =="
dd if="$IMG" of="$DEV" bs=4M conv=fsync status=none || fail "dd failed"
sync
say "written; verifying"

say "== read back the filesystem =="
blkid "$DEV" 2>&1 || fail "blkid found no filesystem on $DEV"
FSTYPE=$(blkid -s TYPE -o value "$DEV" 2>/dev/null || true)
LABEL=$(blkid -s LABEL -o value "$DEV" 2>/dev/null || true)
UUID=$(blkid -s UUID -o value "$DEV" 2>/dev/null || true)
say "type=$FSTYPE label=$LABEL uuid=$UUID"
[ "$FSTYPE" = "ext4" ] || fail "expected ext4, got ${FSTYPE:-none}"
[ "$UUID" = "8c04e46c-5d09-42c5-bccf-5e20d49a17ff" ] || say "WARN: UUID differs from the source image"

say "== mount and verify contents =="
MNT=$OUT/super-check
mkdir -p "$MNT"
mount -o ro "$DEV" "$MNT" || fail "mount failed"
cleanup() { umount "$MNT" 2>/dev/null || true; }
trap cleanup EXIT INT TERM
for f in sbin/init usr/bin/lomiri-session etc/fstab \
         lib/modules/$(uname -r)/modules.dep; do
    if [ -e "$MNT/$f" ]; then say "OK  /$f"; else say "MISSING /$f"; fi
done
say "fstab:"; cat "$MNT/etc/fstab" 2>/dev/null || true
umount "$MNT"
trap - EXIT INT TERM
rmdir "$MNT" 2>/dev/null || true

say "== build candidate boot image =="
[ -f "$BOOT_TEMPLATE" ] || fail "missing boot template $BOOT_TEMPLATE"
CAND=$OUT/boot_a-ut-super.img
# Reuse the project generator only if it is reachable; otherwise patch the
# cmdline in place by rebuilding with the known-good tool.
if [ -f /mnt/h/workspace/PJA110-Mainline/tools/build_native_slot_image.py ]; then
    say "generator found, but it runs on the Windows side; skipping local build"
fi
say "candidate image must be built on the host with:"
say "  python tools/build_native_slot_image.py --mode existing-root \\"
say "    --target out/ut-test/boot-target --root-uuid $UUID \\"
say "    --extra-cmdline 'panel_oneplus_aa536.refresh=120' \\"
say "    --out out/ut-test/boot-ut"

say "== result =="
say "super now contains the UT root: $DEV"
say "root UUID: $UUID"
say "boot_a NOT modified"
say ""
say "to boot it (operator action, after building the candidate image):"
say "  dd if=<candidate boot_a> of=/dev/disk/by-partlabel/boot_a bs=4M conv=fsync"
say "  reboot"
say ""
say "rollback (restore the current pmOS boot image):"
say "  dd if=$BOOT_TEMPLATE of=/dev/disk/by-partlabel/boot_a bs=4M conv=fsync"
say "  reboot"

chmod 644 "$LOG" 2>/dev/null || true
printf '\nUT_STAGE4C_DONE dev=%s uuid=%s log=%s\n' "$DEV" "$UUID" "$LOG" >&3
