#!/bin/sh
# Stage 1: validate the Ubuntu Touch session assets inside the chroot.
#
# Installs the portable pieces this project adds on top of noble's packaging:
#   - /etc/deviceinfo/devices/xigua.yaml     (deviceinfo for PJA110)
#   - /usr/bin/lomiri-session.sh             (session launcher, since noble has
#                                             no lomiri-session binary)
# then starts a session through that launcher and collects logs.
#
# Unlike the earlier probes, this does not run lomiri directly: it exercises the
# same entry point a real systemd session would use, so a failure here means the
# asset is wrong, not the ad-hoc command line.
#
#   sudo -i
#   sh /home/penguin/ut-test/ut-stage1-session.sh
#
# greetd is stopped for the run (DRM master is exclusive) and restored on exit.
set -eu
ROOTFS=${ROOTFS:-/opt/geekbench-rootfs}
SRC=${SRC:-/home/penguin/ut-test}
OUT=${OUT:-/home/penguin/ut-test}
RUN_SECONDS=${RUN_SECONDS:-40}
LOG=$OUT/ut-stage1-$(date +%Y%m%d-%H%M%S).log
INNER=/tmp/lomiri-session-stage1.log
mkdir -p "$OUT"
exec 3>&1 4>&2
exec >>"$LOG" 2>&1
say() { printf '%s\n' "$*"; }
fail() {
    say "FAIL: $*"
    chmod 644 "$LOG" 2>/dev/null || true
    { printf '\nUT_STAGE1_FAILED: %s\nlog: %s\n' "$*" "$LOG"; tail -n 40 "$LOG"; } >&3
    exit 1
}

[ "$(id -u)" = 0 ] || fail "run as root (sudo -i)"
[ -d "$ROOTFS/usr" ] || fail "missing rootfs $ROOTFS"
[ -f "$SRC/xigua.yaml" ] || fail "missing $SRC/xigua.yaml"
[ -f "$SRC/lomiri-session.sh" ] || fail "missing $SRC/lomiri-session.sh"

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

say "== install session assets =="
mkdir -p "$ROOTFS/etc/deviceinfo/devices"
cp "$SRC/xigua.yaml" "$ROOTFS/etc/deviceinfo/devices/xigua.yaml"
cp "$SRC/lomiri-session.sh" "$ROOTFS/usr/bin/lomiri-session"
chmod 755 "$ROOTFS/usr/bin/lomiri-session"
say "installed:"
ls -l "$ROOTFS/etc/deviceinfo/devices/xigua.yaml" "$ROOTFS/usr/bin/lomiri-session"

say "== deviceinfo parse check =="
chroot "$ROOTFS" /bin/sh -c '
  set -x
  ls /usr/lib/aarch64-linux-gnu/ | grep -i deviceinfo || true
  python3 -c "import yaml,sys;d=yaml.safe_load(open(\"/etc/deviceinfo/devices/xigua.yaml\"));print(\"keys:\",list(d[\"xigua\"].keys()))" 2>&1 || true
' || true

if [ "${STOP_SESSION:-1}" = 1 ]; then
    say "== stopping greetd =="
    systemctl stop greetd || say "WARN: greetd stop failed"
    SESSION_STOPPED=1
    sleep 2
fi

say "== start session via /usr/bin/lomiri-session (${RUN_SECONDS}s) =="
rm -f "$ROOTFS$INNER"
chroot "$ROOTFS" /bin/sh -c "
  export XDG_RUNTIME_DIR=/run/user/0
  set -x
  timeout $RUN_SECONDS dbus-run-session -- /usr/bin/lomiri-session >'$INNER' 2>&1
  echo \"lomiri_rc=\$?\"
" || say "WARN: session run exited non-zero"

say "== inner log: head =="
head -25 "$ROOTFS$INNER" 2>/dev/null || true
say "== inner log: tail =="
tail -60 "$ROOTFS$INNER" 2>/dev/null || true
say "== inner log: vsync summary =="
grep -o "interval [0-9.]*ms ([0-9.]*Hz)" "$ROOTFS$INNER" 2>/dev/null | tail -5 || true
say "== inner log: failures =="
grep -nEi "error|failed|cannot|segmentation|abort|not installed" "$ROOTFS$INNER" 2>/dev/null | head -30 || true

say "== copy inner log =="
cp "$ROOTFS$INNER" "$OUT/lomiri-stage1-session.log" 2>/dev/null && say "copied to $OUT/lomiri-stage1-session.log" || say "copy failed"

say "== uninstall? no; assets stay installed for the next stage =="

chmod 644 "$LOG" 2>/dev/null || true
printf '\nUT_STAGE1_DONE log=%s inner=%s\n' "$LOG" "$OUT/lomiri-stage1-session.log" >&3
