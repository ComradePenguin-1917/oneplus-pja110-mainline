#!/bin/sh
# Minimal Lomiri session probe, v5.
#
# v4 failed before doing anything: apt-get install aborted on a non-existent
# package name (lomiri-ui-toolkit), so neither lomiri nor qtmir got installed.
# v5 installs package-by-package only when the name exists, then discovers the
# real session entry point instead of assuming /usr/bin/lomiri.
#
#   sudo -i
#   sh /home/penguin/ut-test/lomiri-probe5.sh
#
# greetd is stopped for the duration and restored on exit.
set -eu
ROOTFS=${ROOTFS:-/opt/geekbench-rootfs}
OUT=${OUT:-/home/penguin/ut-test}
STOP_SESSION=${STOP_SESSION:-1}
LOG=$OUT/lomiri-probe5-$(date +%Y%m%d-%H%M%S).log
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

say "== apt update =="
chroot "$ROOTFS" /bin/sh -c 'export DEBIAN_FRONTEND=noninteractive; apt-get update -qq 2>&1 | tail -3'

say "== install package-by-package, only if the name exists =="
for pkg in lomiri lomiri-system-settings qtmir lomiri-app-launch \
           qml-module-lomiri-components qml-module-lomiri-thumbnailer \
           lomiri-schemas lomiri-sounds dbus-x11; do
    if chroot "$ROOTFS" /bin/sh -c "apt-cache show '$pkg' >/dev/null 2>&1"; then
        say "installing $pkg"
        chroot "$ROOTFS" /bin/sh -c \
            "export DEBIAN_FRONTEND=noninteractive; apt-get install -y --no-install-recommends '$pkg' 2>&1 | tail -4" \
            || say "WARN: $pkg install failed"
    else
        say "SKIP $pkg (not in index)"
    fi
done

say "== inventory =="
chroot "$ROOTFS" /bin/sh -c '
  dpkg -l 2>/dev/null | awk "/lomiri|qtmir/ {print \$2, \$3}" | head -20
  echo "--- binaries ---"
  ls /usr/bin/ | grep -iE "lomiri|qtmir|mir" | head -20
  echo "--- sessions ---"
  ls /usr/share/wayland-sessions/ 2>&1
  ls /usr/share/xsessions/ 2>&1
  echo "--- desktop files ---"
  grep -rl "lomiri" /usr/share/wayland-sessions/ 2>/dev/null
' || true

say "== locate lomiri session executable =="
LOMIRI_BIN=""
for cand in /usr/bin/lomiri /usr/bin/lomiri-session /usr/libexec/lomiri/lomiri \
            /usr/bin/unity8 /usr/bin/unity8-dash; do
    if chroot "$ROOTFS" /bin/sh -c "test -x '$cand'"; then
        say "found $cand"
        LOMIRI_BIN=${LOMIRI_BIN:-$cand}
    fi
done
say "selected: ${LOMIRI_BIN:-none}"

if [ "$STOP_SESSION" = 1 ]; then
    say "== stopping greetd =="
    systemctl stop greetd || say "WARN: greetd stop failed"
    SESSION_STOPPED=1
    sleep 2
fi

if [ -n "$LOMIRI_BIN" ]; then
    say "== start $LOMIRI_BIN on Mir gbm-kms (25s) =="
    chroot "$ROOTFS" /bin/sh -c "
      export XDG_RUNTIME_DIR=/run/user/0
      export QT_QPA_PLATFORM=ubuntumirclient
      export MIR_SERVER_PLATFORM_PATH=/usr/lib/aarch64-linux-gnu/mir/server-platform
      set -x
      timeout 25 dbus-run-session -- '$LOMIRI_BIN' \
          --platform-display-libs mir:gbm-kms \
          --platform-rendering-libs mir:egl-generic \
          --display-report=log 2>&1 | head -120
      echo \"rc=\$?\"
    " || say "WARN: lomiri start failed"
else
    say "no lomiri executable found; only Mir itself is available"
fi

say "== dmesg DRM tail =="
dmesg 2>/dev/null | grep -iE "msm|drm|dsi|panel" | tail -8 || true

chmod 644 "$LOG" 2>/dev/null || true
printf '\nLOMIRI_PROBE_DONE log=%s\n' "$LOG" >&3
