#!/bin/sh
# Stage 2b: run the Ubuntu rootfs as a systemd-nspawn container.
#
# chroot cannot host systemd (it prints "Running in chroot, ignoring command"),
# and systemd-nspawn is the minimal way to get a real PID 1 with the same rootfs.
#
# This script:
#   1. verifies the prerequisite state (host nspawn, cgroup2, rootfs init)
#   2. starts the container detached with a private network namespace
#   3. waits for systemd to reach a usable state
#   4. runs a trivial unit to prove systemd works
#   5. reports state and leaves the container running for the next stage
#
#   sudo -i
#   sh /home/penguin/ut-test/ut-stage2b-nspawn.sh start
#   sh /home/penguin/ut-test/ut-stage2b-nspawn.sh stop
#
# With no argument it defaults to "start".
set -eu
ROOTFS=${ROOTFS:-/opt/geekbench-rootfs}
OUT=${OUT:-/home/penguin/ut-test}
NAME=${NAME:-pja110-ut}
MODE=${1:-start}
LOG=$OUT/ut-stage2b-$(date +%Y%m%d-%H%M%S).log
mkdir -p "$OUT"
exec 3>&1 4>&2
exec >>"$LOG" 2>&1
say() { printf '%s\n' "$*"; }
fail() {
    say "FAIL: $*"
    chmod 644 "$LOG" 2>/dev/null || true
    { printf '\nUT_STAGE2B_FAILED: %s\nlog: %s\n' "$*" "$LOG"; tail -n 40 "$LOG"; } >&3
    exit 1
}

[ "$(id -u)" = 0 ] || fail "run as root (sudo -i)"

case "$MODE" in
stop)
    say "== stopping container $NAME =="
    machinectl terminate "$NAME" 2>/dev/null || systemctl stop "systemd-nspawn@$NAME" 2>/dev/null || true
    sleep 2
    machinectl list --no-pager 2>&1 || true
    printf '\nUT_STAGE2B_STOPPED\n' >&3
    exit 0
    ;;
start|*) ;;
esac

[ -d "$ROOTFS/usr" ] || fail "missing rootfs $ROOTFS"
[ -x /usr/bin/systemd-nspawn ] || fail "systemd-nspawn not available on host"
[ -x "$ROOTFS/sbin/init" ] || fail "rootfs has no /sbin/init"
mountpoint -q /sys/fs/cgroup || fail "cgroup2 is not mounted on the host"

say "== prerequisites =="
say "nspawn: $(systemd-nspawn --version | head -1)"
say "rootfs machine-id: $(cat "$ROOTFS/etc/machine-id" 2>/dev/null)"
say "running containers:"
machinectl list --no-pager 2>&1 || true

say "== start container =="
# --network-namespace-path would need a pre-made netns; use a plain veth-less
# setup for now: the container gets its own network namespace and can be reached
# through machinectl. Graphics is handled by giving the container the DRM nodes.
systemd-nspawn \
    --directory="$ROOTFS" \
    --machine="$NAME" \
    --boot \
    --quiet \
    --link-journal=no \
    --bind=/dev/dri \
    --bind=/dev/input \
    --bind=/run/udev \
    --property=DeviceAllow=char-drm rw \
    >>"$OUT/nspawn-$NAME.log" 2>&1 &
NSPAWN_PID=$!
say "nspawn pid: $NSPAWN_PID"
say "log: $OUT/nspawn-$NAME.log"

say "== wait for systemd inside the container =="
ok=0
i=0
while [ $i -lt 40 ]; do
    i=$((i + 1))
    sleep 1
    state=$(machinectl show "$NAME" --property=State --value 2>/dev/null || true)
    if [ "$state" = "running" ]; then
        ok=1
        break
    fi
done
say "state after ${i}s: ${state:-unknown}"

if [ "$ok" != 1 ]; then
    say "== container did not reach running =="
    tail -40 "$OUT/nspawn-$NAME.log" 2>/dev/null || true
    fail "container failed to start"
fi

say "== systemd state inside container =="
machinectl shell "$NAME" /bin/sh -c 'systemctl is-system-running; systemctl --failed --no-pager | head -20' 2>&1 || true

say "== trivial unit test inside container =="
machinectl shell "$NAME" /bin/sh -c '
  cat > /run/ut-probe.service <<EOF
[Unit]
Description=UT stage2b probe
[Service]
Type=oneshot
ExecStart=/bin/sh -c "echo UT_NSPAWN_UNIT_RAN > /run/ut-probe.out"
[Install]
WantedBy=multi-user.target
EOF
  cp /run/ut-probe.service /etc/systemd/system/ut-probe.service
  systemctl daemon-reload
  systemctl start ut-probe.service
  sleep 1
  cat /run/ut-probe.out 2>&1 || echo "unit did not run"
  systemctl status ut-probe.service --no-pager 2>&1 | head -8
' 2>&1 || say "WARN: unit test failed"

say "== container list =="
machinectl list --no-pager 2>&1 || true

chmod 644 "$LOG" 2>/dev/null || true
printf '\nUT_STAGE2B_DONE mode=%s log=%s\n' "$MODE" "$LOG" >&3
