#!/bin/sh
# Lomiri session probe, v6.
#
# v5 findings: Lomiri -> QtMir -> Mir(gbm-kms) -> DRM/msm chain works; QtMir
# created its MirServer and bound PlatformScreen 1240x2772@119.99 (portrait).
# It only failed at the very end because Mir server options were passed to
# lomiri's own argument parser:
#   lomiri: Unknown options: platform-display-libs, platform-rendering-libs, display-report.
#
# v6 passes those through Mir's environment variables instead, and adds:
#   - touch/input device enumeration inside the session
#   - framebuffer evidence (fb0 content check via gbm? none; instead dmesg + screen)
#   - a longer run so the Lomiri shell can settle
#
#   sudo -i
#   sh /home/penguin/ut-test/lomiri-probe6.sh
#
# greetd is stopped for the duration (DRM master is exclusive) and restored on exit.
set -eu
ROOTFS=${ROOTFS:-/opt/geekbench-rootfs}
OUT=${OUT:-/home/penguin/ut-test}
STOP_SESSION=${STOP_SESSION:-1}
RUN_SECONDS=${RUN_SECONDS:-40}
LOG=$OUT/lomiri-probe6-$(date +%Y%m%d-%H%M%S).log
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

say "== input devices visible in chroot =="
chroot "$ROOTFS" /bin/sh -c '
  for e in /dev/input/event*; do
      [ -e "$e" ] || continue
      n=$(cat "/sys/class/input/${e##*/}/device/name" 2>/dev/null)
      echo "$e -> $n"
  done
' || true

if [ "$STOP_SESSION" = 1 ]; then
    say "== stopping greetd to free DRM master =="
    systemctl stop greetd || say "WARN: greetd stop failed"
    SESSION_STOPPED=1
    sleep 2
fi

say "== run lomiri with Mir platform via environment (${RUN_SECONDS}s) =="
chroot "$ROOTFS" /bin/sh -c "
  export XDG_RUNTIME_DIR=/run/user/0
  export MIR_SERVER_PLATFORM_DISPLAY_LIBS=mir:gbm-kms
  export MIR_SERVER_PLATFORM_RENDERING_LIBS=mir:egl-generic
  export MIR_SERVER_PLATFORM_INPUT_LIB=mir:evdev-input
  export MIR_SERVER_DISPLAY_REPORT=log
  export QT_QPA_PLATFORM=ubuntumirclient
  set -x
  timeout $RUN_SECONDS dbus-run-session -- /usr/bin/lomiri 2>&1 | head -200
  echo \"rc=\$?\"
" || say "WARN: lomiri run exited non-zero"

say "== post-run: was anything drawing? =="
chroot "$ROOTFS" /bin/sh -c '
  ls -l /dev/fb0 2>&1
  cat /sys/class/graphics/fb0/virtual_size 2>&1
' || true

say "== dmesg: DRM/panel =="
dmesg 2>/dev/null | grep -iE "msm|drm|dsi|panel|aa536" | tail -12 || true

chmod 644 "$LOG" 2>/dev/null || true
printf '\nLOMIRI_PROBE_DONE log=%s\n' "$LOG" >&3
