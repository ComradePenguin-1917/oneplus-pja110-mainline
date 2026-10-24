#!/bin/sh
# Mir (gbm-kms) feasibility probe, v2.
#
# v1 findings: EGL/GLES via GBM works (freedreno FD740, GLES 3.2); the Mir smoke
# test never actually started because the platform option name was wrong, and
# XDG_RUNTIME_DIR was unset. This version fixes both and adds libdrm-tests.
#
#   sudo -i
#   sh /home/penguin/ut-test/mir-gbm-probe2.sh
#
# Nothing outside the chroot is modified; /dev /proc /sys are bind-mounted for
# the duration and unmounted on exit.
set -eu
ROOTFS=${ROOTFS:-/opt/geekbench-rootfs}
OUT=${OUT:-/home/penguin/ut-test}
LOG=$OUT/mir-gbm-probe2-$(date +%Y%m%d-%H%M%S).log
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
cleanup() {
    for m in $MOUNTS; do umount "$m" 2>/dev/null || true; done
    say "cleaned up mounts"
}
trap cleanup EXIT INT TERM

mountpoint -q "$ROOTFS/dev"  || { mount --bind /dev "$ROOTFS/dev";  MOUNTS="$ROOTFS/dev $MOUNTS"; }
mountpoint -q "$ROOTFS/proc" || { mount -t proc proc "$ROOTFS/proc"; MOUNTS="$ROOTFS/proc $MOUNTS"; }
mountpoint -q "$ROOTFS/sys"  || { mount --bind /sys "$ROOTFS/sys";   MOUNTS="$ROOTFS/sys $MOUNTS"; }
cp /etc/resolv.conf "$ROOTFS/etc/resolv.conf" 2>/dev/null || true
mkdir -p "$ROOTFS/run/user/0"
chmod 700 "$ROOTFS/run/user/0"

say "== install libdrm-tests (modetest) =="
chroot "$ROOTFS" /bin/sh -c '
  export DEBIAN_FRONTEND=noninteractive
  apt-get install -y --no-install-recommends libdrm-tests 2>&1 | tail -5
' || say "WARN: libdrm-tests install failed"

say "== modetest: connectors/encoders on msm =="
chroot "$ROOTFS" /bin/sh -c '
  set -x
  timeout 10 modetest -M msm -c 2>&1 | head -40
' || say "WARN: modetest failed (DRM master may be held by Phoc)"

say "== Mir platform options =="
chroot "$ROOTFS" /bin/sh -c '
  export XDG_RUNTIME_DIR=/run/user/0
  set -x
  miral-app --help 2>&1 | head -30
  echo "---"
  /usr/lib/aarch64-linux-gnu/mir/server-platform/graphics-gbm-kms.so.20 2>&1 | head -5
' || true

say "== Mir gbm-kms smoke test (12s) =="
chroot "$ROOTFS" /bin/sh -c '
  export XDG_RUNTIME_DIR=/run/user/0
  export MIR_SERVER_PLATFORM_PATH=/usr/lib/aarch64-linux-gnu/mir/server-platform
  set -x
  timeout 12 miral-app --platform gbm-kms 2>&1 | head -50
  echo "rc=$?"
' || say "WARN: miral-app gbm-kms run failed"
