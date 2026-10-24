#!/bin/sh
# Option B, step 1: repartition /dev/sda14 and lay down a direct ext4 UT root.
#
# Current layout of sda14: an MBR table with
#   p1  480 MiB   (pmOS /boot in the loop image)
#   p2  456 GiB   (pmOS root in the loop image)
# Option B replaces that with:
#   p1  512 MiB   reserved (unused for now, keeps room for a future /boot)
#   p2  rest      UT root, ext4, label ut-root, directly mounted (no loop)
#
# THIS DESTROYS pmOS. It runs in two stages so nothing irreversible happens
# without an explicit confirmation:
#
#   sudo -i
#   sh /home/penguin/ut-test/ut-optionb-partition.sh plan     # read-only
#   sh /home/penguin/ut-test/ut-optionb-partition.sh write    # destructive
#
# Before "write" the script verifies:
#   - the UT root image exists and is readable
#   - the pmOS boot/vendor_boot backups exist (rollback of the boot chain)
#   - /dev/sda14 is not mounted and has no holders
set -eu
ROOTFS=${ROOTFS:-/opt/geekbench-rootfs}
OUT=${OUT:-/home/penguin/ut-test}
IMG=${IMG:-/var/lib/ut-root/ut-root.img}
DISK=${DISK:-/dev/sda14}
UT_LABEL=ut-root
LOG=$OUT/ut-optionb-$(date +%Y%m%d-%H%M%S).log
mkdir -p "$OUT"
exec 3>&1 4>&2
exec >>"$LOG" 2>&1
say() { printf '%s\n' "$*"; }
fail() {
    say "FAIL: $*"
    chmod 644 "$LOG" 2>/dev/null || true
    { printf '\nUT_OPTIONB_FAILED: %s\nlog: %s\n' "$*" "$LOG"; tail -n 40 "$LOG"; } >&3
    exit 1
}

[ "$(id -u)" = 0 ] || fail "run as root (sudo -i)"
MODE=${1:-plan}

say "== current state of $DISK =="
say "size: $(cat /sys/class/block/$(basename "$DISK")/size | awk '{printf "%.0f GiB", $1*512/1024/1024/1024}')"
say "mounted: $(mount | grep -c "^$DISK" || true)"
say "holders: $(ls /sys/class/block/$(basename "$DISK")/holders/ 2>/dev/null | tr '\n' ' ')"
say "loop0 backing: $(losetup -l 2>/dev/null | grep sda14 || echo none)"

say "== UT root image =="
[ -f "$IMG" ] || fail "missing $IMG"
say "$IMG: $(du -h "$IMG" | cut -f1), UUID $(blkid -s UUID -o value "$IMG" 2>/dev/null)"

say "== rollback assets =="
for f in /var/lib/ut-root/backup-*/boot_a.img /var/lib/ut-root/backup-*/vendor_boot_a.img \
         /var/lib/ut-root/backup-*/modem_a.img; do
    [ -f "$f" ] && say "present: $f" || say "MISSING: $f"
done

if [ "$MODE" = "plan" ]; then
    say ""
    say "PLAN (destructive):"
    say "  wipe the MBR table on $DISK"
    say "  create p1 512 MiB, p2 (rest) as ext4 label $UT_LABEL"
    say "  copy $IMG onto p2"
    say "  pmOS root inside the loop image will be gone"
    say ""
    say "run with 'write' to execute"
    printf '\nUT_OPTIONB_PLAN_DONE log=%s\n' "$LOG" >&3
    exit 0
fi

[ "$MODE" = "write" ] || fail "usage: $0 plan|write"

say "== preflight for destructive write =="
[ -n "$(mount | grep "^$DISK" || true)" ] && fail "$DISK is mounted"
[ -n "$(ls /sys/class/block/$(basename "$DISK")/holders/ 2>/dev/null)" ] && fail "$DISK has holders"
if losetup -l 2>/dev/null | grep -q "$(basename "$DISK")"; then
    say "detaching loop devices backed by $DISK"
    for l in $(losetup -l -O NAME,BACK-FILE --noheadings 2>/dev/null | awk -v d="$(basename "$DISK")" '$2 ~ d {print $1}'); do
        say "detach $l"
        losetup -d "$l" 2>/dev/null || say "WARN: could not detach $l"
    done
fi
ls /var/lib/ut-root/backup-*/boot_a.img >/dev/null 2>&1 || fail "no boot_a backup; refusing"
ls /var/lib/ut-root/backup-*/vendor_boot_a.img >/dev/null 2>&1 || fail "no vendor_boot_a backup; refusing"

say "== wipe and partition $DISK =="
wipefs -a "$DISK" || fail "wipefs failed"
# MBR with two primary partitions: 512 MiB + rest.
parted -s "$DISK" mklabel msdos || fail "mklabel failed"
parted -s "$DISK" mkpart primary ext4 1MiB 513MiB || fail "p1 failed"
parted -s "$DISK" mkpart primary ext4 513MiB 100% || fail "p2 failed"
sync
partprobe "$DISK" 2>/dev/null || true
sleep 1
say "new layout:"
cat /proc/partitions | grep "$(basename "$DISK")" || true

P2=${DISK}p2
[ -b "$P2" ] || P2=${DISK}2
[ -b "$P2" ] || fail "cannot find the new second partition"

say "== format p2 as ext4, label $UT_LABEL =="
mkfs.ext4 -q -L "$UT_LABEL" -F "$P2" || fail "mkfs failed"
UUID=$(blkid -s UUID -o value "$P2" 2>/dev/null || true)
[ -n "$UUID" ] || fail "no UUID on $P2"
say "UUID: $UUID"

say "== copy UT root onto $P2 =="
MNT=$OUT/utb-mnt
mkdir -p "$MNT"
mount "$P2" "$MNT" || fail "mount $P2 failed"
cleanup() { umount "$MNT" 2>/dev/null || true; }
trap cleanup EXIT INT TERM

tmpimg=$OUT/utb-loop.img
cp --sparse=always "$IMG" "$tmpimg" || fail "copy image failed"
LOOP=$(losetup -f --show -P "$tmpimg") || fail "losetup failed"
say "loop: $LOOP"
mount -o ro "${LOOP}p1" "$OUT/utb-src" 2>/dev/null || { mkdir -p "$OUT/utb-src"; mount -o ro "${LOOP}p1" "$OUT/utb-src"; }
say "copying (tar preserves owners/xattrs)"
tar -C "$OUT/utb-src" -cf - . 2>/dev/null | tar -C "$MNT" -xf - || fail "copy failed"
sync
umount "$OUT/utb-src" 2>/dev/null || true
losetup -d "$LOOP" 2>/dev/null || true
rm -f "$tmpimg"

say "== write fstab with the real UUID =="
cat > "$MNT/etc/fstab" <<EOF
# PJA110 Ubuntu Touch root filesystem
UUID=$UUID  /	ext4  defaults,noatime  0  1
EOF
sync
say "fstab:"; cat "$MNT/etc/fstab"

say "== verify =="
for f in sbin/init usr/bin/lomiri-session etc/fstab lib/modules/$(uname -r)/modules.dep; do
    [ -e "$MNT/$f" ] && say "OK  /$f" || say "MISSING /$f"
done
umount "$MNT"
trap - EXIT INT TERM

say ""
say "DONE. root UUID for the boot cmdline: $UUID"
say "next: build boot image with root=UUID=$UUID and fastboot boot it"
printf '\nUT_OPTIONB_DONE dev=%s uuid=%s log=%s\n' "$P2" "$UUID" "$LOG" >&3
