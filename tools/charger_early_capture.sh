#!/bin/sh
# Read existing kernel interfaces only; never change charging policy.
set -u
umask 077
boot=$(cat /proc/sys/kernel/random/boot_id)
dir=/var/log/pja110-charger/$boot
mkdir -p "$dir" || exit 1
exec >>"$dir/state.txt" 2>&1
echo BEGIN_CHARGER_CAPTURE
uname -a
cat /proc/cmdline
echo ROOT_COMPATIBLE
tr '\000' '\n' </sys/firmware/devicetree/base/compatible
echo PD_MAPPER_MODULE_IDENTITY
modinfo qcom_pd_mapper 2>/dev/null || true
find /lib/modules/$(uname -r) -name 'qcom_pd_mapper.ko*' -exec sha256sum '{}' ';' 2>/dev/null || true
cat /etc/UPower/UPower.conf 2>/dev/null || true
n=0
while [ "$n" -lt 18 ]; do
    echo SNAPSHOT "$n"
    cat /proc/uptime
    for p in /sys/class/power_supply/*; do
        [ -r "$p/uevent" ] || continue
        echo SUPPLY "$p"
        cat "$p/uevent"
    done
    for p in /sys/class/remoteproc/remoteproc*; do
        [ -r "$p/state" ] || continue
        echo REMOTEPROC "$p"
        cat "$p/name" "$p/state" "$p/firmware"
    done
    ls -l /sys/bus/platform/devices/pmic-glink/driver /sys/bus/auxiliary/devices /sys/bus/rpmsg/devices /sys/class/typec 2>/dev/null || true
    cat /proc/modules
    echo AUXILIARY_BINDINGS
    for p in /sys/bus/auxiliary/devices/*; do
        [ -d "$p" ] || continue
        echo DEVICE "$p"
        readlink "$p/driver" || true
        cat "$p/uevent" 2>/dev/null || true
    done
    dmesg >"$dir/dmesg.txt" 2>&1 || true
    sync
    n=$((n + 1))
    sleep 2
done
timeout 4 journalctl -b --no-pager -u upower.service >"$dir/upower.txt" 2>&1 || true
echo END_CHARGER_CAPTURE
sync
