#!/bin/sh
# Run Geekbench 6 (glibc, aarch64) on postmarketOS inside a minimal Ubuntu
# 24.04 arm64 chroot.  Nothing outside /opt/geekbench-rootfs is modified, and
# the rootfs is mounted only for the duration of the run.
#
#   sudo -i
#   sh /home/penguin/geekbench-chroot/run-geekbench.sh --version
#   sh /home/penguin/geekbench-chroot/run-geekbench.sh            # full CPU run
#
# Environment overrides: ROOTFS, GBDIR, TARBALL, LOGDIR.
#
# Why a chroot: Geekbench is a closed-source glibc binary; postmarketOS uses
# musl and gcompat lacks several symbols it needs (__pow_finite,
# __register_atfork, __sprintf_chk, makecontext, ...).  A chroot keeps the
# host kernel, scheduler, CPU frequency and thermal behaviour, so the score is
# comparable; proot would add ptrace overhead to every syscall.
set -eu

ROOTFS=${ROOTFS:-/opt/geekbench-rootfs}
GBDIR=${GBDIR:-/home/penguin/Geekbench-6.7.2-LinuxARMPreview}
TARBALL=${TARBALL:-/home/penguin/geekbench-chroot/ubuntu-base-24.04.3-base-arm64.tar.gz}
LOGDIR=${LOGDIR:-/home/penguin/geekbench-chroot}
LOG=$LOGDIR/run-$(date +%Y%m%d-%H%M%S).log

say() { printf '%s\n' "$*"; }
fail() { printf 'FAIL: %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" = 0 ] || fail "run as root (sudo -i)"
[ -d "$GBDIR" ] || fail "missing Geekbench directory $GBDIR"
[ -x "$GBDIR/geekbench6" ] || fail "missing $GBDIR/geekbench6"
mkdir -p "$LOGDIR"
exec 3>&1 4>&2
exec >>"$LOG" 2>&1

say "geekbench chroot run $(date -Is)"
say "rootfs=$ROOTFS gbdir=$GBDIR"

if [ ! -x "$ROOTFS/bin/sh" ]; then
    [ -f "$TARBALL" ] || fail "rootfs not extracted and tarball missing: $TARBALL"
    say "extracting rootfs (one-time)"
    mkdir -p "$ROOTFS"
    tar -xzf "$TARBALL" -C "$ROOTFS" || fail "rootfs extraction failed"
fi

# DNS for the optional upload / licence check; harmless otherwise.
if [ -f /etc/resolv.conf ]; then
    cp /etc/resolv.conf "$ROOTFS/etc/resolv.conf"
fi
mkdir -p "$ROOTFS/proc" "$ROOTFS/sys" "$ROOTFS/dev/pts" "$ROOTFS/tmp" \
         "$ROOTFS/dev/shm" "$ROOTFS/geekbench"

MOUNTS=""
cleanup() {
    for m in $MOUNTS; do
        umount "$m" 2>/dev/null || true
    done
    say "cleaned up mounts"
}
trap cleanup EXIT INT TERM

mountpoint -q "$ROOTFS/proc"    || { mount --bind /proc "$ROOTFS/proc"; MOUNTS="$ROOTFS/proc $MOUNTS"; }
mountpoint -q "$ROOTFS/sys"     || { mount --bind /sys "$ROOTFS/sys"; MOUNTS="$ROOTFS/sys $MOUNTS"; }
mountpoint -q "$ROOTFS/dev"     || { mount --bind /dev "$ROOTFS/dev"; MOUNTS="$ROOTFS/dev $MOUNTS"; }
mountpoint -q "$ROOTFS/geekbench" || { mount --bind "$GBDIR" "$ROOTFS/geekbench"; MOUNTS="$ROOTFS/geekbench $MOUNTS"; }

say "rootfs ready; running: geekbench6 $*"
if [ "$#" -eq 0 ]; then
    chroot "$ROOTFS" /bin/sh -c 'cd /geekbench && exec ./geekbench6'
else
    chroot "$ROOTFS" /bin/sh -c 'cd /geekbench && exec ./geekbench6 "$@"' sh "$@"
fi
rc=$?
say "geekbench exit code: $rc"
say "log: $LOG"
chmod 644 "$LOG" 2>/dev/null || true
printf '\nGEEKBENCH_DONE rc=%s log=%s\n' "$rc" "$LOG" >&3
exit "$rc"
