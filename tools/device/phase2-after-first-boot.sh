#!/bin/sh
# PJA110 baseline upgrade, phase 2: run after the first normal reboot.
#
#   sudo -i
#   sh /home/penguin/pja110-install/phase2-after-first-boot.sh
#
# Verifies the new kernel/modules, then disables the temporary units and parks
# the legacy /usr/local files (backed up first).  No hot module unload.
set -eu
D=/home/penguin/pja110-install
LOG=$D/phase2-$(date +%Y%m%d-%H%M%S).log
exec 3>&1 4>&2
exec >>"$LOG" 2>&1
say() { printf '%s\n' "$*"; }
step() { say ""; say "== $* =="; }
fail() {
    say "FAIL: $*"
    chmod 644 "$LOG" 2>/dev/null || true
    { printf '\nPHASE2_FAILED: %s\nfull log: %s\n' "$*" "$LOG"; tail -n 40 "$LOG"; } >&3
    exit 1
}

say "PJA110 baseline phase 2  $(date -Is)"
[ "$(id -u)" = 0 ] || fail "run as root (sudo -i)"
# Guard against running this before phase 1 (the package install is the marker).
apk info -e "linux-oneplus-xigua=6.14-r2" >/dev/null ||
    fail "phase 1 has not been applied: linux-oneplus-xigua 6.14-r2 is not installed"
apk info -e "device-oneplus-xigua=1-r7" >/dev/null ||
    fail "phase 1 has not been applied: device-oneplus-xigua 1-r7 is not installed"
[ -d /var/lib/pja110-baseline ] ||
    fail "no phase-1 backup found under /var/lib/pja110-baseline"

step "running system"
uname -r
cat /proc/sys/kernel/random/boot_id
systemctl is-system-running || true
systemctl --failed --no-pager || true

step "loaded modules"
for m in qcom_battmgr qcom_spmi_adc5_gen3 qcom_vadc_common; do
    [ -d "/sys/module/$m" ] || fail "$m is not loaded"
    say "$m version=$(cat /sys/module/$m/version 2>/dev/null)"
done
battmgr_version=$(cat /sys/module/qcom_battmgr/version)
[ "$battmgr_version" = "pja110-single-battery-1" ] || fail "battmgr version is $battmgr_version"
for m in qcom_battmgr qcom_spmi_adc5_gen3; do
    f=$(modinfo -F filename "$m")
    case "$f" in
        /lib/modules/*) say "$m resolves to $f" ;;
        *) fail "$m resolves to $f, not the packaged path" ;;
    esac
done

step "battery topology"
ls /sys/class/power_supply/
[ ! -e /sys/class/power_supply/qcom-battmgr-bat ] || fail "placeholder GLINK battery is back"
[ -d /sys/class/power_supply/bq28z610-0 ] || fail "real BQ battery missing"
[ -d /sys/class/power_supply/qcom-battmgr-usb ] || fail "GLINK USB supply missing"

step "ADC"
grep -qx spmi-adc5-gen3 /sys/bus/iio/devices/iio:device0/name || fail "ADC IIO device missing"
for f in /sys/bus/iio/devices/iio:device0/in_temp*_input; do
    [ -f "$f" ] && say "$f = $(cat "$f")"
done

step "migration check"
/usr/libexec/pja110-migrate-baseline check || true

step "migration apply"
/usr/libexec/pja110-migrate-baseline apply || fail "migration apply failed"

step "post-apply state"
systemctl daemon-reload
systemctl is-enabled pja110-boot-success.service || true
if [ -e /etc/systemd/system/pja110-boot-success.service ]; then
    fail "the legacy unit override is still present after apply"
fi
find /usr/local/lib/pja110 /usr/local/libexec -maxdepth 1 -name 'pja110*' 2>/dev/null || true

chmod 644 "$LOG" 2>/dev/null || true
printf '\nPHASE2_OK log: %s\nReboot normally, then run phase 3 as root:\n  sh %s/phase3-final-check.sh\n' "$LOG" "$D" >&3
trap - EXIT
