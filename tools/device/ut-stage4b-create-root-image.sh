#!/bin/sh
# Stage 4b: create the UT root image from the prepared rootfs.
#
# What this does (and deliberately does not do):
#   + creates a sparse ext4 image at /var/lib/ut-root/ut-root.img
#   + copies the prepared rootfs into it, labels it ut-root
#   + prints the UUID/LABEL and the free space afterwards
#   - does NOT touch the running root, the existing loop device or boot_a
#   - does NOT flash or reboot anything
#
# The image is created on the running root filesystem, which lives on a loop
# device; that is the same arrangement the current system already uses.
#
#   sudo -i
#   sh /home/penguin/ut-test/ut-stage4b-create-root-image.sh [size-MiB]
#
# Default size is 6144 MiB.
set -eu
ROOTFS=${ROOTFS:-/opt/geekbench-rootfs}
OUT=${OUT:-/home/penguin/ut-test}
DEST_DIR=${DEST_DIR:-/var/lib/ut-root}
IMG=$DEST_DIR/ut-root.img
SIZE_MB=${1:-6144}
LOG=$OUT/ut-stage4b-$(date +%Y%m%d-%H%M%S).log
mkdir -p "$OUT"
exec 3>&1 4>&2
exec >>"$LOG" 2>&1
say() { printf '%s\n' "$*"; }
fail() {
    say "FAIL: $*"
    chmod 644 "$LOG" 2>/dev/null || true
    { printf '\nUT_STAGE4B_FAILED: %s\nlog: %s\n' "$*" "$LOG"; tail -n 40 "$LOG"; } >&3
    exit 1
}

[ "$(id -u)" = 0 ] || fail "run as root (sudo -i)"
[ -d "$ROOTFS/usr" ] || fail "missing rootfs $ROOTFS"
[ -d "$ROOTFS/lib/modules" ] || fail "rootfs was not prepared (run 4a first)"

say "== space check =="
avail_mb=$(df -Pm / | awk 'NR==2 {print $4}')
say "available on /: ${avail_mb} MiB"
need=$((SIZE_MB + 512))
[ "$avail_mb" -ge "$need" ] || fail "need ${need} MiB, only ${avail_mb} MiB available"

say "== rootfs size =="
src_kb=$(du -sk "$ROOTFS" 2>/dev/null | tail -1 | awk '{print $1}')
say "rootfs: $((src_kb / 1024)) MiB"
[ "$src_kb" -lt $((SIZE_MB * 1024)) ] || fail "rootfs does not fit in ${SIZE_MB} MiB"

mkdir -p "$DEST_DIR"
if [ -e "$IMG" ]; then
    say "existing image found:"
    ls -lh "$IMG"
    fail "refusing to overwrite $IMG; move it aside first"
fi

say "== create sparse ext4 image (${SIZE_MB} MiB) =="
truncate -s "${SIZE_MB}M" "$IMG" || fail "truncate failed"
mkfs.ext4 -q -L ut-root -F "$IMG" || fail "mkfs.ext4 failed"
say "created $IMG"

say "== mount and copy rootfs =="
MNT=$DEST_DIR/mnt
mkdir -p "$MNT"
mountpoint -q "$MNT" && umount "$MNT" || true
mount -o loop "$IMG" "$MNT" || fail "loop mount failed"
cleanup_mount() { umount "$MNT" 2>/dev/null || true; }
trap cleanup_mount EXIT INT TERM

say "copying (this takes a few minutes)"
tar -C "$ROOTFS" -cf - . 2>/dev/null | tar -C "$MNT" -xf - || fail "copy failed"
sync
say "copied; image usage:"
df -h "$MNT" | tail -1

say "== write fstab with the real root =="
UUID=$(blkid -s UUID -o value "$IMG" 2>/dev/null || true)
[ -n "$UUID" ] || fail "could not read image UUID"
say "root UUID: $UUID"
cat > "$MNT/etc/fstab" <<EOF
# PJA110 Ubuntu Touch root filesystem
UUID=$UUID  /	ext4  defaults,noatime  0  1
EOF
sync

say "== sanity checks inside the image =="
for f in sbin/init usr/bin/lomiri-session lib/modules/$(uname -r)/modules.dep \
         etc/deviceinfo/devices/xigua.yaml usr/lib/systemd/user/lomiri-session.service; do
    if [ -e "$MNT/$f" ]; then say "OK  /$f"; else say "MISSING /$f"; fi
done

say "== unmount =="
umount "$MNT" || fail "unmount failed"
trap - EXIT INT TERM

say "== result =="
ls -lh "$IMG"
say "UUID=$UUID"
say "size: ${SIZE_MB} MiB"

chmod 644 "$LOG" 2>/dev/null || true
printf '\nUT_STAGE4B_DONE image=%s uuid=%s log=%s\n' "$IMG" "$UUID" "$LOG" >&3
