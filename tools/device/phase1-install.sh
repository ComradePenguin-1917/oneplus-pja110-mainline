#!/bin/sh
# PJA110 baseline upgrade, phase 1: preflight, typed backup, package install and
# A-slot boot image update.
#
#   sudo -i
#   sh /home/penguin/pja110-install/phase1-install.sh
#
# Creates one transaction under /var/lib/pja110-baseline/transactions/install-<ts>/
# containing the original boot partitions plus a filesystem archive of the files
# the upgrade replaces (old kernel modules, /boot, packaged units, legacy
# /usr/local files, package version list).  Any failure after the first change
# triggers a rollback of exactly that transaction and reports what remains.
# No userdata access, no slot-B write.
set -eu
D=/home/penguin/pja110-install
STATE=/var/lib/pja110-baseline
LOG=$D/phase1-$(date +%Y%m%d-%H%M%S).log
exec 3>&1 4>&2
exec >>"$LOG" 2>&1
say() { printf '%s\n' "$*"; }
step() { say ""; say "== $* =="; }
changed=0
rolled_back=0
TX=""
TXID=""
fail() {
    say "FAIL: $*"
    chmod 644 "$LOG" 2>/dev/null || true
    { printf '\nPHASE1_FAILED: %s\nfull log: %s\n' "$*" "$LOG"; tail -n 40 "$LOG"; } >&3
    exit 1
}
rollback() {
    [ "$changed" = 1 ] || return 0
    [ "$rolled_back" = 0 ] || return 0
    rolled_back=1
    say ""
    say "ROLLBACK: restoring transaction ${TXID:-?}"
    ok=1
    if [ -n "$TX" ] && [ -f "$TX/meta" ]; then
        if [ -x /usr/libexec/pja110-migrate-baseline ]; then
            /usr/libexec/pja110-migrate-baseline restore --tx "$TXID" || ok=0
        else
            # The package is not installed yet: restore inline.
            for p in boot_a vendor_boot_a; do
                [ -f "$TX/partitions/$p.img" ] || continue
                dd if="$TX/partitions/$p.img" of="/dev/disk/by-partlabel/$p" bs=1M || ok=0
                sync
            done
            [ -f "$TX/files.tar" ] && { tar -C / -xf "$TX/files.tar" || ok=0; }
        fi
    else
        ok=0
    fi
    if [ "$ok" = 1 ]; then
        say "ROLLBACK_OK: boot partitions and files restored from ${TXID}"
        say "NOTE: installed package versions may still be newer; the boot chain and"
        say "      modules are back to the archived files. Check with apk and, if"
        say "      needed, reinstall the previous APKs explicitly."
    else
        say "ROLLBACK_FAILED: manual recovery required"
        say "  pja110-migrate-baseline restore --list"
        say "  pja110-migrate-baseline restore --tx ${TXID:-<id>}"
        say "  transaction dir: ${TX:-missing}"
    fi
}
on_exit() {
    rc=$?
    if [ "$rc" -ne 0 ]; then
        rollback
        printf '\nPHASE1_ABORTED rc=%s tx=%s log=%s\n' "$rc" "${TXID:-none}" "$LOG" >&3
    fi
}
trap on_exit EXIT

say "PJA110 baseline phase 1  $(date -Is)"
[ "$(id -u)" = 0 ] || fail "run as root (sudo -i)"
[ -d "$D" ] || fail "missing $D"

step "preflight: identity"
uname -r
cat /proc/1/comm
tr '\000' '\n' < /proc/device-tree/compatible | head -2
[ "$(uname -r)" = "6.14.0-oneplus-xigua" ] || fail "unexpected kernel"
[ "$(cat /proc/1/comm)" = systemd ] || fail "PID 1 is not systemd"
tr '\000' '\n' < /proc/device-tree/compatible | grep -qx oneplus,xigua || fail "not a PJA110 tree"
findmnt -n -o OPTIONS / | tr ',' '\n' | grep -qx rw || fail "root is not rw"

step "preflight: uploaded artifacts"
expected_linux=93a9c9ba6388b6a0e2a85f6332aea1eab84b8446c70a00953873c9888e4c184f
expected_device=978c9b5df3cddf66cbf5573788b4144a4f5ad63883d7e84cbe6bae4fcdefe636
expected_boot=69a88e8894fd67584d442fa69ba597de8909f272760c5fe585e87e958ce47a12
expected_vendor=d0e6c314cf980d8fadccd1d1c92b8ed783045956d2724cd88f96cae64d40acbd
check_sha() {
    got=$(sha256sum "$1" | cut -d' ' -f1)
    [ "$got" = "$2" ] || fail "$1 sha256 $got != $2"
}
check_sha "$D/linux-oneplus-xigua-6.14-r2.apk" "$expected_linux"
check_sha "$D/device-oneplus-xigua-1-r8.apk" "$expected_device"
check_sha "$D/boot_a.img" "$expected_boot"
check_sha "$D/vendor_boot_a.img" "$expected_vendor"
say "all four uploads match the reviewed hashes"

step "preflight: root UUID matches the generated cmdline"
root_src=$(findmnt -n -o SOURCE /)
root_uuid=$(findmnt -n -o UUID /)
say "root $root_src UUID=$root_uuid"
[ "$root_uuid" = "af27e4ed-0f1f-4976-94a1-46c4c658e55e" ] ||
    fail "running root UUID changed; regenerate the image with the current UUID"
grep -o 'root=UUID=[0-9a-f-]*' "$D/boot_a.img" 2>/dev/null | head -1 || true

step "preflight: partition labels and slot"
mkdir -p /dev/disk/by-partlabel
for f in /sys/class/block/sd*/uevent; do
    label=$(sed -n 's/^PARTNAME=//p' "$f")
    dev=$(sed -n 's/^DEVNAME=//p' "$f")
    case "$label" in
        boot_a|vendor_boot_a|boot_b|init_boot_b|vendor_boot_b|dtbo_b|init_boot_a|dtbo_a)
            test ! -e "/dev/disk/by-partlabel/$label" ||
                test "$(readlink -f "/dev/disk/by-partlabel/$label")" = "/dev/$dev"
            ln -sfn "/dev/$dev" "/dev/disk/by-partlabel/$label"
            ;;
    esac
done
for p in boot_a vendor_boot_a boot_b init_boot_b vendor_boot_b dtbo_b; do
    test -e "/dev/disk/by-partlabel/$p" || fail "missing partition $p"
done
test -c /dev/bsg/ufs-bsg0 || fail "UFS BSG missing"
Q=/usr/bin/qbootctl
[ -x "$Q" ] || Q=/usr/local/libexec/pja110-qbootctl
[ -x "$Q" ] || fail "no qbootctl binary available for the slot check"
say "using $Q for the slot check"
"$Q" -a | tee /tmp/pja110-slot-before.txt
grep -q 'Active slot: _a' /tmp/pja110-slot-before.txt || fail "not running slot A"

step "typed transaction backup"
ts=$(date +%Y%m%d-%H%M%S)
TXID=install-$ts
TX=$STATE/transactions/$TXID
mkdir -p "$TX/partitions" "$TX/files"
: > "$TX/units"
{
    echo "id=$TXID"
    echo "kind=install"
    echo "created=$(date -Is)"
    echo "partitions=boot_a,vendor_boot_a,init_boot_a"
    echo "files=files.tar"
    echo "units=units"
    echo "status=in-progress"
} > "$TX/meta"
for p in boot_a vendor_boot_a init_boot_a; do
    dd if="/dev/disk/by-partlabel/$p" of="$TX/partitions/$p.img" bs=1M 2>/dev/null ||
        fail "backup of $p failed"
done
sha256sum "$TX"/partitions/*.img > "$TX/SHA256SUMS"
for p in boot_b init_boot_b vendor_boot_b dtbo_b; do
    sha256sum "/dev/disk/by-partlabel/$p"
done > "$TX/slot-b-before.txt"
for u in pja110-battmgr-readonly pja110-adc-test pja110-charger-capture \
         pja110-wifi-probe pja110-wifi-clean-boot pja110-wifi-aston-rfkill; do
    systemctl is-enabled --quiet "$u.service" 2>/dev/null && echo "$u.service" >> "$TX/units"
done
apk info -v 2>/dev/null | sort > "$TX/apk_before.txt" || true
tar -C / -cf "$TX/files.tar" \
    boot \
    "lib/modules/$(uname -r)" \
    usr/share/kernel/oneplus-xigua \
    usr/libexec \
    usr/lib/systemd/system \
    usr/lib/systemd/system-preset \
    etc/systemd/system 2>/dev/null || true
say "transaction: $TX"
say "partitions: $(cat "$TX/SHA256SUMS" | wc -l); files.tar: $(du -h "$TX/files.tar" | cut -f1)"
say "old packages: $(grep -E '^(linux-oneplus-xigua|device-oneplus-xigua|qbootctl)-' "$TX/apk_before.txt" | tr '\n' ' ')"
say "restore: pja110-migrate-baseline restore --tx $TXID"

step "install packages"
changed=1
apk policy qbootctl >/dev/null 2>&1 || fail "qbootctl is not available from the configured repositories"
apk add --no-cache qbootctl || fail "could not install qbootctl"
apk add --allow-untrusted --force-overwrite "$D/linux-oneplus-xigua-6.14-r2.apk" ||
    fail "kernel package install failed"
apk add --allow-untrusted --force-overwrite "$D/device-oneplus-xigua-1-r8.apk" ||
    fail "device package install failed"

step "verify installed package content"
release=$(cat /usr/share/kernel/oneplus-xigua/kernel.release)
say "kernel release file: $release"
[ "$release" = "6.14.0-oneplus-xigua" ] || fail "unexpected kernel release file"
apk info -e "linux-oneplus-xigua=6.14-r2" >/dev/null || fail "kernel package is not installed at 6.14-r2"
apk info -e "device-oneplus-xigua=1-r8" >/dev/null || fail "device package is not installed at 1-r8"
test -x /usr/bin/qbootctl || fail "packaged qbootctl missing"
/usr/bin/qbootctl -a | tee /tmp/pja110-slot-before.txt
grep -q 'Active slot: _a' /tmp/pja110-slot-before.txt || fail "not running slot A (packaged qbootctl)"
test -f "/lib/modules/$release/kernel/drivers/power/supply/qcom_battmgr.ko" || fail "battmgr module missing"
test -f "/lib/modules/$release/kernel/drivers/iio/adc/qcom-spmi-adc5-gen3.ko" || fail "ADC module missing"
modinfo -F version "/lib/modules/$release/kernel/drivers/power/supply/qcom_battmgr.ko" |
    grep -qx pja110-single-battery-1 || fail "packaged battmgr version mismatch"
test -x /usr/libexec/pja110-mark-a-success || fail "boot-success script missing"
test -x /usr/libexec/pja110-migrate-baseline || fail "migration script missing"
test -e /usr/lib/systemd/system/pja110-boot-success.service || fail "packaged unit missing"

step "write boot_a"
dd if="$D/boot_a.img" of=/dev/disk/by-partlabel/boot_a bs=1M || fail "boot_a write failed"
sync
got=$(sha256sum /dev/disk/by-partlabel/boot_a | cut -d' ' -f1)
[ "$got" = "$expected_boot" ] || fail "boot_a read-back mismatch ($got)"
say "boot_a verified: $got"

step "write vendor_boot_a (initramfs changed, so kernel and initramfs stay in sync)"
dd if="$D/vendor_boot_a.img" of=/dev/disk/by-partlabel/vendor_boot_a bs=1M ||
    fail "vendor_boot_a write failed"
sync
got=$(sha256sum /dev/disk/by-partlabel/vendor_boot_a | cut -d' ' -f1)
[ "$got" = "$expected_vendor" ] || fail "vendor_boot_a read-back mismatch ($got)"
say "vendor_boot_a verified: $got"

step "confirm slot B untouched"
for p in boot_b init_boot_b vendor_boot_b dtbo_b; do
    now=$(sha256sum "/dev/disk/by-partlabel/$p" | cut -d' ' -f1)
    was=$(sed -n "s|^\([0-9a-f]*\)  /dev/disk/by-partlabel/$p\$|\1|p" "$TX/slot-b-before.txt" 2>/dev/null)
    say "$p now=$now was=$was"
    [ -n "$was" ] || fail "no recorded hash for $p in the transaction"
    [ "$now" = "$was" ] || fail "slot B changed: $p"
done
say "slot B hashes unchanged"

sed -i 's/^status=.*/status=complete/' "$TX/meta"
chmod 644 "$LOG" 2>/dev/null || true
printf '\nPHASE1_OK tx=%s log: %s\nNext: reboot normally, then run phase 2 as root:\n  sh %s/phase2-after-first-boot.sh\n' "$TXID" "$LOG" "$D" >&3
trap - EXIT
