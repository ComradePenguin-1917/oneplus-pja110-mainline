#!/bin/sh
# Stage 4a: prepare the Ubuntu rootfs so it can boot on bare metal.
#
# This only writes inside the rootfs. It does not touch any partition, boot image
# or the running system.
#
# What it does:
#   1. copies the running kernel's modules into the rootfs (version must match
#      exactly, otherwise the kernel cannot load drm/panel/touch/network)
#   2. writes fstab, hostname, machine-id
#   3. installs the session assets (lomiri-session, deviceinfo, user unit)
#   4. verifies the result and prints a report
#
#   sudo -i
#   sh /home/penguin/ut-test/ut-stage4a-prepare-rootfs.sh
set -eu
ROOTFS=${ROOTFS:-/opt/geekbench-rootfs}
SRC=${SRC:-/home/penguin/ut-test}
OUT=${OUT:-/home/penguin/ut-test}
LOG=$OUT/ut-stage4a-$(date +%Y%m%d-%H%M%S).log
mkdir -p "$OUT"
exec 3>&1 4>&2
exec >>"$LOG" 2>&1
say() { printf '%s\n' "$*"; }
fail() {
    say "FAIL: $*"
    chmod 644 "$LOG" 2>/dev/null || true
    { printf '\nUT_STAGE4A_FAILED: %s\nlog: %s\n' "$*" "$LOG"; tail -n 40 "$LOG"; } >&3
    exit 1
}

[ "$(id -u)" = 0 ] || fail "run as root (sudo -i)"
[ -d "$ROOTFS/usr" ] || fail "missing rootfs $ROOTFS"

REL=$(uname -r)
SRC_MODS=/lib/modules/$REL
[ -d "$SRC_MODS" ] || fail "no modules for $REL on the host"

say "== 1. kernel modules =="
say "release: $REL"
say "source size: $(du -sh "$SRC_MODS" | cut -f1)"
mkdir -p "$ROOTFS/lib/modules"
if [ -d "$ROOTFS/lib/modules/$REL" ]; then
    say "modules already present, refreshing"
    rm -rf "$ROOTFS/lib/modules/$REL"
fi
cp -a "$SRC_MODS" "$ROOTFS/lib/modules/$REL"
say "copied to $ROOTFS/lib/modules/$REL"
say "module count: $(find "$ROOTFS/lib/modules/$REL" -name '*.ko*' | wc -l)"
# depmod needs to run with the rootfs' own tooling; use the host depmod but point
# it at the rootfs so modules.dep matches this exact tree.
for tool in /sbin/depmod /usr/sbin/depmod /bin/depmod /usr/bin/depmod; do
    if [ -x "$tool" ]; then
        say "running $tool -b $ROOTFS $REL"
        "$tool" -b "$ROOTFS" "$REL" 2>&1 | tail -5 || say "WARN: depmod failed"
        break
    fi
done
say "modules.dep: $(wc -l < "$ROOTFS/lib/modules/$REL/modules.dep" 2>/dev/null || echo missing)"

say "== 2. system identity files =="
# Root UUID is filled in by the image-creation step; keep a placeholder that is
# obvious if it is ever booted without being set.
if [ ! -s "$ROOTFS/etc/fstab" ] || grep -q "UNCONFIGURED FSTAB" "$ROOTFS/etc/fstab"; then
    cat > "$ROOTFS/etc/fstab" <<'EOF'
# PJA110 Ubuntu Touch root filesystem
# The root entry is written by ut-stage4b when the UT root image is created.
LABEL=ut-root  /      ext4  defaults,noatime  0  1
EOF
    say "wrote placeholder fstab (root via LABEL=ut-root)"
else
    say "fstab already configured, leaving it"
fi

printf 'pja110\n' > "$ROOTFS/etc/hostname"
cat > "$ROOTFS/etc/hosts" <<'EOF'
127.0.0.1 localhost
127.0.1.1 pja110
::1       localhost ip6-localhost ip6-loopback
EOF
say "hostname: $(cat "$ROOTFS/etc/hostname")"

if [ ! -s "$ROOTFS/etc/machine-id" ]; then
    tr -d '-' < /proc/sys/kernel/random/uuid > "$ROOTFS/etc/machine-id"
    say "generated machine-id"
else
    say "machine-id present: $(cat "$ROOTFS/etc/machine-id")"
fi

say "== 3. session assets =="
mkdir -p "$ROOTFS/etc/deviceinfo/devices" "$ROOTFS/usr/lib/systemd/user"
[ -f "$SRC/xigua.yaml" ] && cp "$SRC/xigua.yaml" "$ROOTFS/etc/deviceinfo/devices/xigua.yaml" \
    || say "WARN: $SRC/xigua.yaml missing"
[ -f "$SRC/lomiri-session.sh" ] && { cp "$SRC/lomiri-session.sh" "$ROOTFS/usr/bin/lomiri-session"; chmod 755 "$ROOTFS/usr/bin/lomiri-session"; } \
    || say "WARN: $SRC/lomiri-session.sh missing"
[ -f "$SRC/lomiri-session.service" ] && cp "$SRC/lomiri-session.service" "$ROOTFS/usr/lib/systemd/user/" \
    || say "WARN: $SRC/lomiri-session.service missing"
ls -l "$ROOTFS/usr/bin/lomiri-session" "$ROOTFS/usr/lib/systemd/user/lomiri-session.service" 2>&1 || true

say "== 4. verification =="
say "-- modules for $REL --"
ls "$ROOTFS/lib/modules/$REL/kernel/drivers/gpu/drm/panel/" 2>/dev/null | head -5 || say "panel dir missing"
ls "$ROOTFS/lib/modules/$REL/kernel/drivers/power/supply/" 2>/dev/null | grep -E "battmgr|bq" | head -3 || true
say "-- critical modules present? --"
for m in "kernel/drivers/gpu/drm/panel/panel-oneplus-aa536.ko" \
         "kernel/drivers/power/supply/qcom_battmgr.ko" \
         "kernel/drivers/iio/adc/qcom-spmi-adc5-gen3.ko"; do
    if [ -f "$ROOTFS/lib/modules/$REL/$m" ]; then say "OK  $m"; else say "MISSING $m"; fi
done
say "-- rootfs size --"
du -sh "$ROOTFS" 2>/dev/null | tail -1

chmod 644 "$LOG" 2>/dev/null || true
printf '\nUT_STAGE4A_DONE log=%s\n' "$LOG" >&3
