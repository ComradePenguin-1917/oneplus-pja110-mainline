#!/bin/sh
# Lomiri session probe, v8.
#
# v7 root cause: the inner log path pointed outside the chroot
#   /bin/sh: 9: cannot create /home/penguin/ut-test/lomiri-session.log:
#   Directory nonexistent
# so lomiri never started (rc=2) and the screen stayed black. v8 writes the
# inner log to /tmp inside the chroot (always present) and reads it back through
# $ROOTFS/tmp.
#
#   sudo -i
#   sh /home/penguin/ut-test/lomiri-probe8.sh
#
# greetd is stopped for the run (DRM master is exclusive) and restored on exit.
set -eu
ROOTFS=${ROOTFS:-/opt/geekbench-rootfs}
OUT=${OUT:-/home/penguin/ut-test}
STOP_SESSION=${STOP_SESSION:-1}
RUN_SECONDS=${RUN_SECONDS:-40}
LOG=$OUT/lomiri-probe8-$(date +%Y%m%d-%H%M%S).log
INNER=/tmp/lomiri-session.log
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
mkdir -p "$ROOTFS/run/user/0" "$ROOTFS/dev/dri" "$ROOTFS/tmp"
chmod 700 "$ROOTFS/run/user/0"
chmod 1777 "$ROOTFS/tmp" 2>/dev/null || true

say "== input devices =="
chroot "$ROOTFS" /bin/sh -c '
  for e in /dev/input/event*; do
      [ -e "$e" ] || continue
      echo "$e -> $(cat /sys/class/input/${e##*/}/device/name 2>/dev/null)"
  done
' || true

if [ "$STOP_SESSION" = 1 ]; then
    say "== stopping greetd =="
    systemctl stop greetd || say "WARN: greetd stop failed"
    SESSION_STOPPED=1
    sleep 2
fi

say "== run lomiri (${RUN_SECONDS}s, inner log $INNER inside chroot) =="
rm -f "$ROOTFS$INNER"
chroot "$ROOTFS" /bin/sh -c "
  export XDG_RUNTIME_DIR=/run/user/0
  export MIR_SERVER_PLATFORM_DISPLAY_LIBS=mir:gbm-kms
  export MIR_SERVER_PLATFORM_RENDERING_LIBS=mir:egl-generic
  export MIR_SERVER_DISPLAY_REPORT=log
  export MIR_SERVER_INPUT_REPORT=log
  export QT_QPA_PLATFORM=ubuntumirclient
  set -x
  timeout $RUN_SECONDS dbus-run-session -- /usr/bin/lomiri >'$INNER' 2>&1
  echo \"lomiri_rc=\$?\"
" || say "WARN: lomiri run exited non-zero"

say "== inner log size =="
ls -l "$ROOTFS$INNER" 2>&1 || true
say "== inner log: first 40 lines =="
head -40 "$ROOTFS$INNER" 2>/dev/null || true
say "== inner log: last 100 lines =="
tail -100 "$ROOTFS$INNER" 2>/dev/null || true
say "== inner log: error/QML/shell lines =="
grep -nEi "error|failed|cannot|qml|shell|dash|segmentation|abort|Unsupported" "$ROOTFS$INNER" 2>/dev/null | head -50 || true

say "== copy inner log to host for inspection =="
cp "$ROOTFS$INNER" "$OUT/lomiri-session-$(date +%Y%m%d-%H%M%S).log" 2>/dev/null && say "copied" || say "copy failed"

say "== dmesg DRM/GPU =="
dmesg 2>/dev/null | grep -iE "msm|drm|dsi|panel|gmu|hfi" | tail -12 || true

chmod 644 "$LOG" 2>/dev/null || true
printf '\nLOMIRI_PROBE_DONE log=%s\n' "$LOG" >&3
