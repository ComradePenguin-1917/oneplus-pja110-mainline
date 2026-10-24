#!/bin/sh
# Stage 3a: start Lomiri inside the running nspawn container and see if it draws.
#
# Requirements this script handles:
#   - the container was started with --bind-ro=/dev/dri in stage 2b, which is
#     enough to open the device but not to become DRM master; the container must
#     be restarted with a writable /dev/dri binding first
#   - the host desktop (greetd/phoc) must release DRM master, otherwise Lomiri
#     fails with "Failed to claim DRM master"
#   - Lomiri needs a user session bus and XDG_RUNTIME_DIR inside the container
#
#   sudo -i
#   sh /home/penguin/ut-test/ut-stage3a-lomiri-container.sh
#
# Restores the host session on exit.
set -eu
ROOTFS=${ROOTFS:-/opt/geekbench-rootfs}
OUT=${OUT:-/home/penguin/ut-test}
NAME=${NAME:-pja110-ut}
RUN_SECONDS=${RUN_SECONDS:-45}
LOG=$OUT/ut-stage3a-$(date +%Y%m%d-%H%M%S).log
NLOG=$OUT/nspawn-$NAME.log
INNER=/run/lomiri-stage3a.log
mkdir -p "$OUT"
exec 3>&1 4>&2
exec >>"$LOG" 2>&1
say() { printf '%s\n' "$*"; }
fail() {
    say "FAIL: $*"
    say "== nspawn log tail =="
    tail -30 "$NLOG" 2>/dev/null || true
    chmod 644 "$LOG" 2>/dev/null || true
    { printf '\nUT_STAGE3A_FAILED: %s\nlog: %s\n' "$*" "$LOG"; tail -n 30 "$LOG"; } >&3
    exit 1
}

[ "$(id -u)" = 0 ] || fail "run as root (sudo -i)"
[ -d "$ROOTFS/usr" ] || fail "missing rootfs $ROOTFS"

SESSION_STOPPED=0
cleanup() {
    if [ "$SESSION_STOPPED" = 1 ]; then
        say "restarting greetd"
        systemctl start greetd 2>/dev/null || true
    fi
    say "cleaned up"
}
trap cleanup EXIT INT TERM

say "== stop existing container =="
machinectl terminate "$NAME" 2>/dev/null || true
sleep 3
machinectl list --no-pager 2>&1 || true

say "== clean stale mounts under rootfs =="
for m in "$ROOTFS/dev/pts" "$ROOTFS/dev" "$ROOTFS/proc" "$ROOTFS/sys" "$ROOTFS/run"; do
    if mountpoint -q "$m" 2>/dev/null; then
        say "unmounting $m"
        umount "$m" 2>/dev/null || umount -l "$m" 2>/dev/null || true
    fi
done

say "== restart container with writable DRM =="
: > "$NLOG"
systemd-nspawn \
    --directory="$ROOTFS" \
    --machine="$NAME" \
    --boot \
    --quiet \
    --link-journal=no \
    --bind=/dev/dri \
    --bind=/dev/input \
    --bind=/run/udev \
    >>"$NLOG" 2>&1 &
say "nspawn pid: $!"

ok=0
i=0
while [ $i -lt 45 ]; do
    i=$((i + 1))
    sleep 1
    state=$(machinectl show "$NAME" --property=State --value 2>/dev/null || true)
    [ "$state" = "running" ] && { ok=1; break; }
done
say "container state: ${state:-unknown}"
[ "$ok" = 1 ] || fail "container did not start"

say "== stop host session to free DRM master =="
systemctl stop greetd || say "WARN: greetd stop failed"
SESSION_STOPPED=1
sleep 3
say "phoc instances: $(pgrep -c phoc 2>/dev/null || echo 0)"

say "== confirm DRM is free =="
if [ -e /dev/dri/card0 ]; then
    say "card0 present"
fi

say "== start Lomiri inside container (${RUN_SECONDS}s) =="
machinectl shell "$NAME" /bin/sh -c "
  export XDG_RUNTIME_DIR=/run/user/0
  export HOME=/root
  mkdir -p /run/user/0 && chmod 700 /run/user/0
  dbus-daemon --session --fork --print-address > /run/dbus-addr.txt 2>/dev/null || true
  export DBUS_SESSION_BUS_ADDRESS=\$(cat /run/dbus-addr.txt 2>/dev/null)
  set -x
  timeout $RUN_SECONDS /usr/bin/lomiri-session >'$INNER' 2>&1
  echo \"lomiri_rc=\$?\"
" 2>&1 || say "WARN: lomiri start returned non-zero"

say "== inner log head =="
machinectl shell "$NAME" /bin/sh -c "head -25 '$INNER'" 2>&1 || true
say "== inner log: vsync =="
machinectl shell "$NAME" /bin/sh -c "grep -o 'interval [0-9.]*ms ([0-9.]*Hz)' '$INNER' | tail -5" 2>&1 || true
say "== inner log: failures =="
machinectl shell "$NAME" /bin/sh -c "grep -nEi 'error|failed|cannot|segmentation|abort|not installed' '$INNER' | head -25" 2>&1 || true
say "== inner log tail =="
machinectl shell "$NAME" /bin/sh -c "tail -40 '$INNER'" 2>&1 || true

say "== copy inner log out =="
cp "$ROOTFS$INNER" "$OUT/lomiri-stage3a.log" 2>/dev/null && say "copied" || say "copy failed"

chmod 644 "$LOG" 2>/dev/null || true
printf '\nUT_STAGE3A_DONE log=%s inner=%s\n' "$LOG" "$OUT/lomiri-stage3a.log" >&3
