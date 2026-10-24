#!/bin/sh
# One-shot installer init: copies the prepared UT root onto a raw partition and
# reboots. The boot partitions are flashed separately with fastboot, because a
# ramdisk cannot rewrite the partitions it was loaded from.
#
# Reads the root filesystem image from the first available source:
#   1. /dev/sda6   (super, already contains the ext4 UT root)
#   or a file /flash/ut-root.img if present
# Writes it to /dev/sda14 and reboots.
set -eu
/bin/busybox --install -s

echo "==================================================="
echo " PJA110 Ubuntu Touch root install"
echo "==================================================="

mount -t proc     proc /proc 2>/dev/null || true
mount -t sysfs    sys  /sys  2>/dev/null || true
mount -t devtmpfs dev  /dev  2>/dev/null || true

i=0
while [ $i -lt 60 ]; do
    [ -b /dev/sda6 ] && [ -b /dev/sda14 ] && break
    i=$((i+1)); sleep 1
done
[ -b /dev/sda6 ]  || { echo "FATAL: /dev/sda6 missing";  exec /bin/sh; }
[ -b /dev/sda14 ] || { echo "FATAL: /dev/sda14 missing"; exec /bin/sh; }

SRC=/dev/sda6
if [ -f /flash/ut-root.img ]; then
    SRC=/flash/ut-root.img
fi

echo "source: $SRC"
echo "target: /dev/sda14"
echo "copying (this takes a few minutes)..."

dd if="$SRC" of=/dev/sda14 bs=1M conv=fsync 2>&1 | tail -2
sync

echo "verifying"
uuid=$(blkid -s UUID -o value /dev/sda14 2>/dev/null || true)
label=$(blkid -s LABEL -o value /dev/sda14 2>/dev/null || true)
fstype=$(blkid -s TYPE -o value /dev/sda14 2>/dev/null || true)
echo "filesystem: ${fstype:-unknown}  label=${label:-none}  uuid=${uuid:-none}"
[ "$fstype" = "ext4" ] || { echo "FATAL: target is not ext4"; exec /bin/sh; }

echo "==================================================="
echo " root copied; rebooting"
echo "==================================================="
sleep 5
reboot -f
exec /bin/sh
