#!/bin/sh
# Mir (gbm-kms) feasibility probe, v3.
#
# v2 findings:
#   - DRM side is healthy: modetest shows MSM Snapdragon DRM, DSI-1 connected,
#     1240x2772@120Hz preferred mode.
#   - Mir 2.14 has no "--platform" option; it uses --platform-display-libs /
#     --platform-rendering-libs / --platform-input-lib / --platform-path.
#   - Phoc holds DRM master, so Mir cannot take KMS while the desktop runs.
#
# Usage:
#   sudo -i
#   STOP_SESSION=0 sh mir-gbm-probe3.sh     # keep desktop running (default)
#   STOP_SESSION=1 sh mir-gbm-probe3.sh     # stop greetd for the test, restore after
#
# Nothing outside the chroot is modified except, with STOP_SESSION=1, greetd is
# stopped for the duration of the probe and started again on exit.
set -eu
ROOTFS=${ROOTFS:-/opt/geekbench-rootfs}
OUT=${OUT:-/home/penguin/ut-test}
STOP_SESSION=${STOP_SESSION:-0}
LOG=$OUT/mir-gbm-probe3-$(date +%Y%m%d-%H%M%S).log
mkdir -p "$OUT"
exec 3>&1 4>&2
exec >>"$LOG" 2>&1
say() { printf '%s\n' "$*"; }
fail() {
    say "FAIL: $*"
    chmod 644 "$LOG" 2>/dev/null || true
    { printf '\nMIR_PROBE_FAILED: %s\nlog: %s\n' "$*" "$LOG"; tail -n 40 "$LOG"; } >&3
    exit 1
}

[ "$(id -u)" = 0 ] || fail "run as root (sudo -i)"
[ -d "$ROOTFS/usr" ] || fail "missing rootfs $ROOTFS"

MOUNTS=""
SESSION_STOPPED=0
cleanup() {
    for m in $MOUNTS; do umount "$m" 2>/dev/null || true; done
    if [ "$SESSION_STOPPED" = 1 ]; then
        say "restarting greetd"
        systemctl start greetd 2>/dev/null || true
    fi
    say "cleaned up"
}
trap cleanup EXIT INT TERM

mountpoint -q "$ROOTFS/dev"  || { mount --bind /dev "$ROOTFS/dev";  MOUNTS="$ROOTFS/dev $MOUNTS"; }
mountpoint -q "$ROOTFS/proc" || { mount -t proc proc "$ROOTFS/proc"; MOUNTS="$ROOTFS/proc $MOUNTS"; }
mountpoint -q "$ROOTFS/sys"  || { mount --bind /sys "$ROOTFS/sys";   MOUNTS="$ROOTFS/sys $MOUNTS"; }
cp /etc/resolv.conf "$ROOTFS/etc/resolv.conf" 2>/dev/null || true
mkdir -p "$ROOTFS/run/user/0"
chmod 700 "$ROOTFS/run/user/0"
mkdir -p "$ROOTFS/dev/dri"

say "== preconditions =="
say "STOP_SESSION=$STOP_SESSION"
if [ "$STOP_SESSION" = 1 ]; then
    say "stopping greetd to free DRM master"
    systemctl stop greetd || say "WARN: greetd stop failed"
    SESSION_STOPPED=1
    sleep 2
fi
say "DRM master holders:"
fuser -v /dev/dri/card0 2>&1 || true

say "== Mir explicit gbm-kms run (15s) =="
chroot "$ROOTFS" /bin/sh -c '
  export XDG_RUNTIME_DIR=/run/user/0
  export MIR_SERVER_PLATFORM_PATH=/usr/lib/aarch64-linux-gnu/mir/server-platform
  set -x
  timeout 15 miral-app \
      --platform-display-libs gbm-kms \
      --platform-rendering-libs egl-generic \
      --compositor-report=log \
      --display-report=log 2>&1 | head -80
  echo "rc=$?"
' || say "WARN: explicit gbm-kms run failed"

say "== Mir autodetect run (10s) =="
chroot "$ROOTFS" /bin/sh -c '
  export XDG_RUNTIME_DIR=/run/user/0
  set -x
  timeout 10 miral-app --display-report=log 2>&1 | head -40
  echo "rc=$?"
' || say "WARN: autodetect run failed"

say "== miral-kiosk (simpler, 10s) =="
chroot "$ROOTFS" /bin/sh -c '
  export XDG_RUNTIME_DIR=/run/user/0
  set -x
  timeout 10 miral-kiosk \
      --platform-display-libs gbm-kms \
      --platform-rendering-libs egl-generic \
      --display-report=log 2>&1 | head -40
  echo "rc=$?"
' || say "WARN: miral-kiosk failed"

say "== dmesg tail (DRM/msm) =="
dmesg 2>/dev/null | tail -20 || true

chmod 644 "$LOG" 2>/dev/null || true
printf '\nMIR_PROBE_DONE log=%s\n' "$LOG" >&3
