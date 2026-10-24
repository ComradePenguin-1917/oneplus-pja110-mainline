#!/bin/sh
# Stage 2a: can systemd --user run inside the chroot without logind?
#
# Everything except the rootfs sysctl check runs *inside* the chroot, because
# the rootfs binaries are glibc/aarch64 and the host is musl: running them from
# the host fails with __isoc23_* relocation errors.
#
# This probe does not start Lomiri. It only asks:
#   1. does rootfs systemctl work inside the chroot
#   2. does `systemd --user` start and reach running state
#   3. can it start a trivial user unit
#
#   sudo -i
#   sh /home/penguin/ut-test/ut-stage2a-systemd-user.sh
set -eu
ROOTFS=${ROOTFS:-/opt/geekbench-rootfs}
OUT=${OUT:-/home/penguin/ut-test}
LOG=$OUT/ut-stage2a-$(date +%Y%m%d-%H%M%S).log
mkdir -p "$OUT"
exec 3>&1 4>&2
exec >>"$LOG" 2>&1
say() { printf '%s\n' "$*"; }
fail() {
    say "FAIL: $*"
    chmod 644 "$LOG" 2>/dev/null || true
    { printf '\nUT_STAGE2A_FAILED: %s\nlog: %s\n' "$*" "$LOG"; tail -n 40 "$LOG"; } >&3
    exit 1
}

[ "$(id -u)" = 0 ] || fail "run as root (sudo -i)"
[ -d "$ROOTFS/usr" ] || fail "missing rootfs $ROOTFS"

MOUNTS=""
cleanup() {
    for m in $MOUNTS; do umount "$m" 2>/dev/null || true; done
    say "cleaned up"
}
trap cleanup EXIT INT TERM

for d in dev proc sys; do
    mountpoint -q "$ROOTFS/$d" || {
        if [ "$d" = proc ]; then mount -t proc proc "$ROOTFS/proc"
        else mount --bind "/$d" "$ROOTFS/$d"; fi
        MOUNTS="$ROOTFS/$d $MOUNTS"
    }
done
mkdir -p "$ROOTFS/run/user/0" "$ROOTFS/tmp" "$ROOTFS/run/systemd"
chmod 700 "$ROOTFS/run/user/0"
chmod 1777 "$ROOTFS/tmp" 2>/dev/null || true

say "== 1. systemctl inside chroot =="
chroot "$ROOTFS" /usr/bin/systemctl --version 2>&1 | head -3 || fail "systemctl does not run inside chroot"

say "== 2. start systemd --user and query it =="
chroot "$ROOTFS" /bin/sh -c '
  export XDG_RUNTIME_DIR=/run/user/0
  export HOME=/root
  unset DBUS_SESSION_BUS_ADDRESS
  set -x
  # systemd --user needs a session bus; systemd itself provides the user manager
  # on the private socket, so start it detached first.
  /usr/bin/dbus-daemon --session --fork --print-address > /tmp/dbus-addr.txt 2>/tmp/dbus-err.txt || true
  cat /tmp/dbus-addr.txt 2>/dev/null
  cat /tmp/dbus-err.txt 2>/dev/null
  export DBUS_SESSION_BUS_ADDRESS=$(cat /tmp/dbus-addr.txt 2>/dev/null)
  echo "bus=$DBUS_SESSION_BUS_ADDRESS"
  timeout 20 /lib/systemd/systemd --user --unit=basic.target > /tmp/systemd-user.log 2>&1 &
  USER_PID=$!
  sleep 6
  echo "--- is-system-running ---"
  /usr/bin/systemctl --user is-system-running 2>&1 || true
  echo "--- list-units (first 15) ---"
  /usr/bin/systemctl --user list-units --no-pager 2>&1 | head -15 || true
  echo "--- systemd-user.log ---"
  head -30 /tmp/systemd-user.log 2>/dev/null || true
  echo "--- stop ---"
  kill $USER_PID 2>/dev/null || true
  wait $USER_PID 2>/dev/null || true
  echo done
' || say "WARN: systemd --user probe returned non-zero"

say "== 3. can a trivial user unit start? =="
chroot "$ROOTFS" /bin/sh -c '
  export XDG_RUNTIME_DIR=/run/user/0
  export HOME=/root
  mkdir -p /etc/systemd/user
  cat > /etc/systemd/user/ut-probe.service <<EOF
[Unit]
Description=UT stage2a probe unit

[Service]
Type=oneshot
ExecStart=/bin/sh -c "echo UT_PROBE_UNIT_RAN > /tmp/ut-probe.out"

[Install]
WantedBy=default.target
EOF
  if [ -f /tmp/dbus-addr.txt ]; then export DBUS_SESSION_BUS_ADDRESS=$(cat /tmp/dbus-addr.txt); fi
  set -x
  timeout 20 /lib/systemd/systemd --user > /tmp/systemd-user2.log 2>&1 &
  USER_PID=$!
  sleep 5
  /usr/bin/systemctl --user daemon-reload 2>&1 || true
  /usr/bin/systemctl --user start ut-probe.service 2>&1 || true
  sleep 2
  cat /tmp/ut-probe.out 2>&1 || echo "unit did not run"
  /usr/bin/systemctl --user status ut-probe.service --no-pager 2>&1 | head -12 || true
  kill $USER_PID 2>/dev/null || true
  wait $USER_PID 2>/dev/null || true
' || say "WARN: probe unit run failed"

say "== 4. cgroup view inside chroot =="
chroot "$ROOTFS" /bin/sh -c 'cat /proc/self/cgroup; ls /sys/fs/cgroup 2>&1 | head -8' || true

chmod 644 "$LOG" 2>/dev/null || true
printf '\nUT_STAGE2A_DONE log=%s\n' "$LOG" >&3
