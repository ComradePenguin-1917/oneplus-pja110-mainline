#!/bin/sh
# Stage 2b v2: run the Ubuntu rootfs as a systemd-nspawn container.
#
# v1 failed because the rootfs still had a devtmpfs bind-mounted on /dev left
# over from the earlier chroot probes:
#   /tmp/nspawn-root-.../dev/ is pre-mounted and pre-populated
#   Failed to create /dev/pts: File exists
# nspawn refuses a pre-populated /dev, so v2:
#   - unmounts any stale mounts under the rootfs first
#   - does not bind the whole /dev; binds only /dev/dri and /dev/input read-only
#   - prints the nspawn log on failure
#
#   sudo -i
#   sh /home/penguin/ut-test/ut-stage2b-nspawn2.sh          # start
#   sh /home/penguin/ut-test/ut-stage2b-nspawn2.sh stop     # stop
set -eu
ROOTFS=${ROOTFS:-/opt/geekbench-rootfs}
OUT=${OUT:-/home/penguin/ut-test}
NAME=${NAME:-pja110-ut}
MODE=${1:-start}
LOG=$OUT/ut-stage2b2-$(date +%Y%m%d-%H%M%S).log
NLOG=$OUT/nspawn-$NAME.log
mkdir -p "$OUT"
exec 3>&1 4>&2
exec >>"$LOG" 2>&1
say() { printf '%s\n' "$*"; }
fail() {
    say "FAIL: $*"
    say "== nspawn log tail =="
    tail -40 "$NLOG" 2>/dev/null || true
    chmod 644 "$LOG" 2>/dev/null || true
    { printf '\nUT_STAGE2B_FAILED: %s\nlog: %s\n' "$*" "$LOG"; tail -n 30 "$LOG"; } >&3
    exit 1
}

[ "$(id -u)" = 0 ] || fail "run as root (sudo -i)"

case "$MODE" in
stop)
    say "== stopping container $NAME =="
    machinectl terminate "$NAME" 2>/dev/null || true
    sleep 2
    machinectl list --no-pager 2>&1 || true
    printf '\nUT_STAGE2B_STOPPED\n' >&3
    exit 0
    ;;
start|*) ;;
esac

[ -d "$ROOTFS/usr" ] || fail "missing rootfs $ROOTFS"
[ -x /usr/bin/systemd-nspawn ] || fail "systemd-nspawn not available"
[ -x "$ROOTFS/sbin/init" ] || fail "rootfs has no /sbin/init"
mountpoint -q /sys/fs/cgroup || fail "cgroup2 not mounted on host"

say "== clean stale mounts under rootfs =="
for m in "$ROOTFS/dev/pts" "$ROOTFS/dev" "$ROOTFS/proc" "$ROOTFS/sys" "$ROOTFS/run"; do
    if mountpoint -q "$m" 2>/dev/null; then
        say "unmounting $m"
        umount "$m" 2>/dev/null || umount -l "$m" 2>/dev/null || say "WARN: could not unmount $m"
    fi
done
say "remaining mounts under rootfs:"
mount | grep "$ROOTFS" || say "(none)"

say "== start container =="
: > "$NLOG"
systemd-nspawn \
    --directory="$ROOTFS" \
    --machine="$NAME" \
    --boot \
    --quiet \
    --link-journal=no \
    --bind-ro=/dev/dri \
    --bind-ro=/dev/input \
    --bind=/run/udev \
    >>"$NLOG" 2>&1 &
say "nspawn pid: $!"
say "log: $NLOG"

say "== wait for container =="
ok=0
i=0
state=""
while [ $i -lt 45 ]; do
    i=$((i + 1))
    sleep 1
    state=$(machinectl show "$NAME" --property=State --value 2>/dev/null || true)
    if [ "$state" = "running" ]; then
        ok=1
        break
    fi
    if ! pgrep -f "systemd-nspawn.*$NAME" >/dev/null 2>&1; then
        say "nspawn process exited early"
        break
    fi
done
say "state after ${i}s: ${state:-unknown}"

[ "$ok" = 1 ] || fail "container did not reach running"

say "== systemd state inside container =="
machinectl shell "$NAME" /bin/sh -c 'systemctl is-system-running || true; echo "--- failed ---"; systemctl --failed --no-pager | head -20' 2>&1 || true

say "== trivial unit inside container =="
machinectl shell "$NAME" /bin/sh -c '
  printf "[Unit]\nDescription=UT probe\n[Service]\nType=oneshot\nExecStart=/bin/sh -c \"echo UT_NSPAWN_UNIT_RAN > /run/ut-probe.out\"\n[Install]\nWantedBy=multi-user.target\n" > /etc/systemd/system/ut-probe.service
  systemctl daemon-reload
  systemctl start ut-probe.service
  sleep 1
  cat /run/ut-probe.out 2>&1 || echo "unit did not run"
' 2>&1 || say "WARN: unit test failed"

say "== container list =="
machinectl list --no-pager 2>&1 || true

chmod 644 "$LOG" 2>/dev/null || true
printf '\nUT_STAGE2B_DONE mode=%s log=%s nlog=%s\n' "$MODE" "$LOG" "$NLOG" >&3
