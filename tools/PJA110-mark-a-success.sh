#!/bin/sh
set -eu
test "$(uname -r)" = 6.14.0-oneplus-xigua
test "$(cat /proc/1/comm)" = systemd
tr '\000' '\n' < /sys/firmware/devicetree/base/compatible | grep -qx oneplus,xigua
findmnt -n -o OPTIONS / | tr ',' '\n' | grep -qx rw
test -c /dev/bsg/ufs-bsg0
mkdir -p /dev/disk/by-partlabel
for f in /sys/class/block/sd*/uevent; do
    label=$(sed -n 's/^PARTNAME=//p' "$f")
    dev=$(sed -n 's/^DEVNAME=//p' "$f")
    case "$label" in
        boot_a|boot_b|xbl_a|xbl_b|abl_a|abl_b)
            test ! -e "/dev/disk/by-partlabel/$label" ||
                test "$(readlink -f "/dev/disk/by-partlabel/$label")" = "/dev/$dev"
            ln -sfn "/dev/$dev" "/dev/disk/by-partlabel/$label"
            ;;
    esac
done
q=/usr/local/libexec/pja110-qbootctl
"$q" -a | grep -F 'Active slot: _a'
ready=0
for i in $(seq 1 30); do
    up=$(cut -d . -f 1 /proc/uptime)
    if [ "$up" -ge 45 ] && systemctl is-active --quiet sshd.service &&
            systemctl is-active --quiet greetd.service && pgrep -x phoc >/dev/null; then
        ready=1
        break
    fi
    sleep 2
done
test "$ready" = 1
before=$("$q" -n 1)
printf '%s\n' "$before" | grep -F 'SLOT _b: is marked successful'
"$q" -m 0
sync
"$q" -n 0 | grep -F 'SLOT _a: is marked successful'
test "$("$q" -n 1)" = "$before"
echo PJA110_A_SUCCESS_VERIFIED_B_UNCHANGED
