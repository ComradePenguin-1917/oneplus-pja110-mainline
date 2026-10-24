#!/bin/sh
# Stage 2 probe (read-only): can systemd run inside the chroot?
#
# Starting systemd inside a chroot is the risky part of stage 2: it needs cgroup2
# mounted, /run/systemd present, and it must not fight the host's systemd. This
# probe only inspects, it never starts anything.
#
#   sudo -i
#   sh /home/penguin/ut-test/ut-stage2-probe.sh
set -eu
ROOTFS=${ROOTFS:-/opt/geekbench-rootfs}
OUT=${OUT:-/home/penguin/ut-test}
LOG=$OUT/ut-stage2-probe-$(date +%Y%m%d-%H%M%S).log
mkdir -p "$OUT"
exec 3>&1 4>&2
exec >>"$LOG" 2>&1
say() { printf '%s\n' "$*"; }
fail() {
    say "FAIL: $*"
    { printf '\nUT_STAGE2_PROBE_FAILED: %s\nlog: %s\n' "$*" "$LOG"; tail -n 30 "$LOG"; } >&3
    exit 1
}

[ "$(id -u)" = 0 ] || fail "run as root (sudo -i)"
[ -d "$ROOTFS/usr" ] || fail "missing rootfs $ROOTFS"

say "== host cgroup state =="
stat -fc %T /sys/fs/cgroup
cat /proc/self/cgroup
say "host controllers: $(cat /sys/fs/cgroup/cgroup.controllers 2>/dev/null)"
say "host subtree: $(cat /sys/fs/cgroup/cgroup.subtree_control 2>/dev/null)"

say "== rootfs systemd =="
ls -l "$ROOTFS/lib/systemd/systemd" "$ROOTFS/usr/bin/systemctl" 2>&1
"$ROOTFS/usr/bin/systemctl" --version 2>&1 | head -3 || true

say "== rootfs dirs needed by systemd =="
for d in run run/systemd run/systemd/system etc/systemd var/lib/systemd tmp; do
    if [ -d "$ROOTFS/$d" ]; then
        say "present: /$d"
    else
        say "missing: /$d"
    fi
done

say "== rootfs dbus / logind / accounts =="
for f in usr/bin/dbus-daemon usr/libexec/accounts-daemon lib/systemd/systemd-logind \
         usr/lib/systemd/systemd-logind; do
    [ -e "$ROOTFS/$f" ] && say "present: /$f" || say "missing: /$f"
done

say "== rootfs user units =="
ls "$ROOTFS/usr/lib/systemd/user/" 2>/dev/null | head -20 || true
say "lomiri-session unit installed? $(ls "$ROOTFS/usr/lib/systemd/user/lomiri-session.service" 2>/dev/null || echo no)"

say "== our installed assets =="
ls -l "$ROOTFS/usr/bin/lomiri-session" "$ROOTFS/etc/deviceinfo/devices/xigua.yaml" 2>&1

say "== is anything already bind-mounted into the rootfs? =="
mount | grep -c "$ROOTFS" || true

say "== host systemd PID 1 sanity =="
say "host pid1: $(cat /proc/1/comm)"
say "host systemd version: $(systemctl --version 2>/dev/null | head -1)"

chmod 644 "$LOG" 2>/dev/null || true
printf '\nUT_STAGE2_PROBE_DONE log=%s\n' "$LOG" >&3
