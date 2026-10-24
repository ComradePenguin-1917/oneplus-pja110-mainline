#!/bin/busybox sh
# Minimal initramfs for PJA110 / Ubuntu Touch.
#
#   1. mount the pseudo filesystems
#   2. the GPU firmware is already inside this archive, so the msm/adreno probe
#      at ~0.8 s can load it before the root filesystem exists
#   3. find and mount the root filesystem
#   4. hand over with switch_root
#
# Deliberately plain: no "set -u", no command substitution inside messages, and
# every applet called through /bin/busybox explicitly. Earlier versions failed
# silently because a missing helper left the script without working commands.

BB=/bin/busybox
ROOT_DEV=/dev/sda14
NEWROOT=/newroot

$BB mount -t proc  proc /proc
$BB mount -t sysfs sys  /sys
$BB mkdir -p /dev
$BB mount -t devtmpfs dev /dev

# Print to the panel and to /dev/console, so both a phone without a serial
# cable and a QEMU/serial capture see the same lines.
say() {
    echo "[ut-init] $1"
    if [ -c /dev/tty0 ]; then
        echo "[ut-init] $1" > /dev/tty0
    fi
    if [ -c /dev/console ]; then
        echo "[ut-init] $1" > /dev/console
    fi
}

say "starting"
if [ -f /lib/firmware/qcom/a740_sqe.fw ]; then
    say "gpu firmware present"
else
    say "WARNING: gpu firmware missing"
fi

say "waiting for /dev/sda14"
i=0
while [ $i -lt 60 ]; do
    if [ -b "$ROOT_DEV" ]; then
        break
    fi
    i=$((i + 1))
    $BB sleep 1
done

if [ ! -b "$ROOT_DEV" ]; then
    say "FATAL: root device absent after 60s"
    say "listing /dev"
    $BB ls /dev
    exec $BB sh
fi

say "root device ready"

$BB mkdir -p "$NEWROOT"
if ! $BB mount -o rw,noatime "$ROOT_DEV" "$NEWROOT"; then
    say "FATAL: mount failed"
    exec $BB sh
fi

if [ ! -x "$NEWROOT/sbin/init" ]; then
    say "FATAL: /sbin/init missing"
    exec $BB sh
fi

$BB mkdir -p "$NEWROOT/proc" "$NEWROOT/sys" "$NEWROOT/dev" "$NEWROOT/run"
$BB mount --move /proc "$NEWROOT/proc"
$BB mount --move /sys  "$NEWROOT/sys"
$BB mount --move /dev  "$NEWROOT/dev"

say "switching root"
exec $BB switch_root "$NEWROOT" /sbin/init
