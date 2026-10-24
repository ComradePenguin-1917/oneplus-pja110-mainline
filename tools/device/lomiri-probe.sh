#!/bin/sh
# Minimal Lomiri session probe (Ubuntu Touch UI on mainline Mir), v4.
#
# Context: Mir gbm-kms already works on this device (see probe3 log
# 20261018-141236): DSI-1 1240x2772@119.99, EGL swap OK. This probe installs
# lomiri + qtmir in the Ubuntu 24.04 chroot and tries to start a minimal
# Lomiri shell on Mir's gbm-kms platform.
#
#   sudo -i
#   STOP_SESSION=1 sh /home/penguin/ut-test/lomiri-probe.sh
#
# greetd is stopped for the duration (DRM master is exclusive) and restored on
# exit. Nothing outside the chroot is modified.
set -eu
ROOTFS=${ROOTFS:-/opt/geekbench-rootfs}
OUT=${OUT:-/home/penguin/ut-test}
STOP_SESSION=${STOP_SESSION:-1}
LOG=$OUT/lomiri-probe-$(date +%Y%m%d-%H%M%S).log
mkdir -p "$OUT"
exec 3>&1 4>&2
exec >>"$LOG" 2>&1
say() { printf '%s\n' "$*"; }
fail() {
    say "FAIL: $*"
    chmod 644 "$LOG" 2>/dev/null || true
    { printf '\nLOMIRI_PROBE_FAILED: %s\nlog: %s\n' "$*" "$LOG"; tail -n 40 "$LOG"; } >&3
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
mkdir -p "$ROOTFS/run/user/0" "$ROOTFS/dev/dri"
chmod 700 "$ROOTFS/run/user/0"

say "== install lomiri + qtmir =="
chroot "$ROOTFS" /bin/sh -c '
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq 2>&1 | tail -2
  apt-get install -y --no-install-recommends \
      lomiri lomiri-system-settings qtmir \
      lomiri-ui-toolkit qml-module-lomiri-components \
      lomiri-app-launch dbus-x11 2>&1 | tail -20
' || fail "apt install lomiri failed"

say "== package inventory =="
chroot "$ROOTFS" /bin/sh -c '
  dpkg -l | awk "/lomiri|qtmir|mir/ {print \$2, \$3}" | head -30
' || true

say "== lomiri binaries / session files =="
chroot "$ROOTFS" /bin/sh -c '
  set -x
  command -v lomiri lomiri-system-settings lomiri-app-launch 2>&1
  ls /usr/share/wayland-sessions/ /usr/share/xsessions/ 2>&1
  ls /usr/bin/ | grep -i lomiri | head
' || true

if [ "$STOP_SESSION" = 1 ]; then
    say "== stopping greetd to free DRM master =="
    systemctl stop greetd || say "WARN: greetd stop failed"
    SESSION_STOPPED=1
    sleep 2
fi

say "== start minimal Lomiri on Mir gbm-kms (25s) =="
chroot "$ROOTFS" /bin/sh -c '
  export XDG_RUNTIME_DIR=/run/user/0
  export MIR_SERVER_PLATFORM_PATH=/usr/lib/aarch64-linux-gnu/mir/server-platform
  export QT_QPA_PLATFORM=ubuntumirclient
  export QT_QPA_PLATFORM_PLUGIN_PATH=/usr/lib/aarch64-linux-gnu/qt5/plugins/platforms
  set -x
  timeout 25 lomiri --platform-display-libs mir:gbm-kms \
                    --platform-rendering-libs mir:egl-generic \
                    --display-report=log 2>&1 | head -120
  echo "rc=$?"
' || say "WARN: lomiri start failed"

say "== fallback: miral-app with ubuntumirclient apps =="
chroot "$ROOTFS" /bin/sh -c '
  export XDG_RUNTIME_DIR=/run/user/0
  set -x
  timeout 15 miral-app --display-report=log 2>&1 | head -40
  echo "rc=$?"
' || say "WARN: fallback failed"

say "== dmesg DRM tail =="
dmesg 2>/dev/null | grep -iE "msm|drm|dsi" | tail -10 || true

chmod 644 "$LOG" 2>/dev/null || true
printf '\nLOMIRI_PROBE_DONE log=%s\n' "$LOG" >&3
