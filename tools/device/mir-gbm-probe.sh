#!/bin/sh
# Minimal Mir (gbm backend) feasibility test inside the Ubuntu 24.04 arm64 chroot.
# Does not touch the running system: the chroot gets /dev, /proc, /sys bind-mounted
# for the duration of the test and is unmounted afterwards.
#
#   sudo -i
#   sh /home/penguin/ut-test/mir-gbm-probe.sh
#
# Result summary is printed and saved to /home/penguin/ut-test/mir-gbm-probe.log.
set -eu
ROOTFS=${ROOTFS:-/opt/geekbench-rootfs}
OUT=${OUT:-/home/penguin/ut-test}
LOG=$OUT/mir-gbm-probe-$(date +%Y%m%d-%H%M%S).log
mkdir -p "$OUT"
exec 3>&1 4>&2
exec >>"$LOG" 2>&1
say() { printf '%s\n' "$*"; }
fail() {
    say "FAIL: $*"
    chmod 644 "$LOG" 2>/dev/null || true
    { printf '\nMIR_PROBE_FAILED: %s\nlog: %s\n' "$*" "$LOG"; tail -n 30 "$LOG"; } >&3
    exit 1
}

[ "$(id -u)" = 0 ] || fail "run as root (sudo -i)"
[ -d "$ROOTFS/usr" ] || fail "missing rootfs $ROOTFS"

MOUNTS=""
cleanup() {
    for m in $MOUNTS; do umount "$m" 2>/dev/null || true; done
    say "cleaned up mounts"
}
trap cleanup EXIT INT TERM

mountpoint -q "$ROOTFS/dev"  || { mount --bind /dev "$ROOTFS/dev";  MOUNTS="$ROOTFS/dev $MOUNTS"; }
mountpoint -q "$ROOTFS/proc" || { mount -t proc proc "$ROOTFS/proc"; MOUNTS="$ROOTFS/proc $MOUNTS"; }
mountpoint -q "$ROOTFS/sys"  || { mount --bind /sys "$ROOTFS/sys";   MOUNTS="$ROOTFS/sys $MOUNTS"; }
cp /etc/resolv.conf "$ROOTFS/etc/resolv.conf" 2>/dev/null || true

say "== 1. DRM/EGL visibility inside chroot =="
chroot "$ROOTFS" /bin/sh -c '
  set -x
  ls -l /dev/dri 2>&1
  ls /usr/lib/aarch64-linux-gnu/libgbm.so* /usr/lib/aarch64-linux-gnu/libEGL.so* 2>&1
  cat /sys/class/drm/card0-DSI-1/modes 2>&1
' || fail "basic DRM visibility failed"

say "== 2. install Mir gbm backend + test tools =="
chroot "$ROOTFS" /bin/sh -c '
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq 2>&1 | tail -3
  apt-get install -y --no-install-recommends \
      mir-platform-graphics-gbm-kms mir-demos \
      libgbm1 libegl1 libgles2 mesa-utils 2>&1 | tail -15
' || fail "apt install failed (check network/mirror in chroot)"

say "== 3. EGL/GBM capability probe =="
chroot "$ROOTFS" /bin/sh -c '
  set -x
  command -v eglinfo && eglinfo -B 2>&1 | head -40
  command -v es2_info && es2_info 2>&1 | head -30
  ls /usr/lib/aarch64-linux-gnu/dri/ 2>&1 | head
' || say "WARN: EGL probe tools missing or failed"

say "== 4. Mir gbm platform smoke test =="
chroot "$ROOTFS" /bin/sh -c '
  set -x
  command -v miral-app || command -v miral-shell || true
  # Minimal Mir server on the gbm-kms platform, 10s then quit
  timeout 12 miral-app --platform-graphics-gbm-kms 2>&1 | head -40
  echo "miral_rc=$?"
' || say "WARN: miral-app run failed"

say "== 5. DRM master / connector state =="
chroot "$ROOTFS" /bin/sh -c '
  set -x
  timeout 10 modetest -M msm -c 2>&1 | head -30
' || say "WARN: modetest unavailable"

chmod 644 "$LOG" 2>/dev/null || true
printf '\nMIR_PROBE_DONE log=%s\n' "$LOG" >&3
