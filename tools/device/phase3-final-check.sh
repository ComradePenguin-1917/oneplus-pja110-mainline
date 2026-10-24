#!/bin/sh
# PJA110 baseline upgrade, phase 3: final acceptance facts that need root.
#
#   sudo -i
#   sh /home/penguin/pja110-install/phase3-final-check.sh
#
# Read-only.  Run after the second reboot (the one following migration).
set -eu
D=/home/penguin/pja110-install
LOG=$D/phase3-$(date +%Y%m%d-%H%M%S).log
exec 3>&1 4>&2
exec >>"$LOG" 2>&1
say() { printf '%s\n' "$*"; }
step() { say ""; say "== $* =="; }
fail() {
    say "FAIL: $*"
    chmod 644 "$LOG" 2>/dev/null || true
    { printf '\nPHASE3_FAILED: %s\nfull log: %s\n' "$*" "$LOG"; tail -n 40 "$LOG"; } >&3
    exit 1
}

say "PJA110 baseline phase 3  $(date -Is)"
[ "$(id -u)" = 0 ] || fail "run as root (sudo -i)"

step "identity"
uname -a
cat /proc/sys/kernel/random/boot_id
cat /proc/1/comm
findmnt -n -o SOURCE,UUID,OPTIONS /
tr '\000' '\n' < /proc/device-tree/compatible | head -2
ls -l /dev/bsg/ufs-bsg0

step "slot state (read-only)"
qbootctl -a
qbootctl -n 0
qbootctl -n 1

step "boot image read-back"
expected_boot=69a88e8894fd67584d442fa69ba597de8909f272760c5fe585e87e958ce47a12
expected_vendor=d0e6c314cf980d8fadccd1d1c92b8ed783045956d2724cd88f96cae64d40acbd
boot_sha=$(sha256sum /dev/disk/by-partlabel/boot_a | cut -d' ' -f1)
vendor_sha=$(sha256sum /dev/disk/by-partlabel/vendor_boot_a | cut -d' ' -f1)
say "boot_a=$boot_sha"
say "vendor_boot_a=$vendor_sha"
[ "$boot_sha" = "$expected_boot" ] || fail "boot_a does not match the generated image"
[ "$vendor_sha" = "$expected_vendor" ] || fail "vendor_boot_a does not match the generated image"

step "slot B unchanged"
# Phase 1 writes slot-b-before.txt inside its install transaction.
B=""
for cand in /var/lib/pja110-baseline/transactions/install-*/; do
    [ -f "$cand/slot-b-before.txt" ] && B=${cand%/}
done
[ -n "$B" ] || fail "no install transaction with slot-b-before.txt found"
say "using transaction: $B"
for p in boot_b init_boot_b vendor_boot_b dtbo_b; do
    now=$(sha256sum "/dev/disk/by-partlabel/$p" | cut -d' ' -f1)
    was=$(grep "/dev/disk/by-partlabel/$p$" "$B/slot-b-before.txt" | cut -d' ' -f1)
    say "$p now=$now was=$was"
    [ -n "$was" ] || fail "no recorded hash for $p in $B"
    [ "$now" = "$was" ] || fail "slot B changed: $p"
done

step "packaged baseline check"
/usr/libexec/pja110-migrate-baseline check || fail "migrate check did not pass"

step "boot-success service"
systemctl is-enabled pja110-boot-success.service
systemctl status pja110-boot-success.service --no-pager || true
journalctl -b -u pja110-boot-success --no-pager | tail -n 30 || true

step "legacy artifacts must be gone"
if [ -e /usr/local/lib/pja110/qcom_battmgr.ko ] ||
   [ -e /usr/local/libexec/pja110-qbootctl ] ||
   [ -e /etc/systemd/system/pja110-boot-success.service ]; then
    fail "legacy artifacts still present"
fi
say "none"

step "temporary units must be disabled"
for u in pja110-battmgr-readonly pja110-adc-test pja110-charger-capture \
         pja110-wifi-probe pja110-wifi-clean-boot pja110-wifi-aston-rfkill; do
    state=$(systemctl is-enabled "$u.service" 2>/dev/null || true)
    say "$u: ${state:-absent}"
    if [ "$state" = "enabled" ]; then
        fail "$u is still enabled"
    fi
done

step "power / thermal summary"
for d in /sys/class/power_supply/*; do
    say "${d##*/}: type=$(cat "$d/type" 2>/dev/null) status=$(cat "$d/status" 2>/dev/null) capacity=$(cat "$d/capacity" 2>/dev/null) current=$(cat "$d/current_now" 2>/dev/null)"
done
for f in /sys/bus/iio/devices/iio:device0/in_temp*_input; do
    [ -f "$f" ] && say "$f = $(cat "$f")"
done

step "warnings"
journalctl -b -k -p warning --no-pager | tail -n 60 || true
systemctl --failed --no-pager || true

chmod 644 "$LOG" 2>/dev/null || true
printf '\nPHASE3_OK log: %s\n' "$LOG" >&3
trap - EXIT
