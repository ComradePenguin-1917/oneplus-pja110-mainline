#!/bin/busybox sh
# Ubuntu Touch initramfs /init — PJA110.
#
# Built from scratch on a static busybox, so there is no interpreter or shared
# library to resolve: the failures seen earlier ("Failed to execute /init
# (error -2)") came from a dynamically linked busybox whose musl loader was not
# reachable at exec time.
#
# The kernel on this device has UFS, the block layer and ext4 built in, but the
# UFS probe finishes after the VFS first tries root=, so mounting root directly
# fails with "unknown-block(0,0)". This script waits for the device instead.
set -u

/bin/busybox --install -s

TARGET_UUID=8c04e46c-5d09-42c5-bccf-5e20d49a17ff
NEWROOT=/newroot

mkdir -p /proc /sys /dev /newroot /tmp
mount -t proc     proc /proc
mount -t sysfs    sys  /sys
mount -t devtmpfs dev  /dev

# Send our messages to the panel as well as the default console.
if [ -c /dev/tty0 ]; then
    exec >/dev/tty0 2>&1
fi

echo "[ut-init] starting"

# Wait for the UT root to appear. UFS enumerates asynchronously.
ROOTDEV=""
i=0
while [ "$i" -lt 120 ]; do
    ROOTDEV=$(blkid -U "$TARGET_UUID" 2>/dev/null)
    if [ -n "$ROOTDEV" ]; then
        break
    fi
    i=$((i+1))
    sleep 1
done

if [ -z "$ROOTDEV" ]; then
    echo "[ut-init] root $TARGET_UUID not found after ${i}s"
    echo "[ut-init] available block devices:"
    ls /dev/sd* 2>/dev/null | head -20
    echo "[ut-init] dropping to a shell"
    exec /bin/sh
fi

echo "[ut-init] root is $ROOTDEV"

if ! mount -o rw,noatime "$ROOTDEV" "$NEWROOT"; then
    echo "[ut-init] mount failed"
    exec /bin/sh
fi

echo "[ut-init] mounted; checking userspace"
if [ ! -x "$NEWROOT/sbin/init" ]; then
    echo "[ut-init] $NEWROOT/sbin/init missing"
    exec /bin/sh
fi

mkdir -p "$NEWROOT/proc" "$NEWROOT/sys" "$NEWROOT/dev" "$NEWROOT/run"
mount --move /proc "$NEWROOT/proc"
mount --move /sys  "$NEWROOT/sys"
mount --move /dev  "$NEWROOT/dev"

echo "[ut-init] switching root"
exec switch_root "$NEWROOT" /sbin/init
