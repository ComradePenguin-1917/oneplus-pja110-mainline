#!/bin/sh
# PJA110 baseline, phase 2b: remove the disabled temporary unit files.
#
#   sudo -i
#   sh /home/penguin/pja110-install/phase2b-cleanup-legacy-units.sh
#
# Phase 2 disabled these units but kept their files.  This backs the files up
# under /var/lib/pja110-baseline and removes them so the packaged baseline has
# no leftover /etc unit overrides.  No partition access.
set -eu
D=/home/penguin/pja110-install
LOG=$D/phase2b-$(date +%Y%m%d-%H%M%S).log
exec 3>&1 4>&2
exec >>"$LOG" 2>&1
say() { printf '%s\n' "$*"; }
fail() {
    say "FAIL: $*"
    chmod 644 "$LOG" 2>/dev/null || true
    { printf '\nPHASE2B_FAILED: %s\nfull log: %s\n' "$*" "$LOG"; tail -n 30 "$LOG"; } >&3
    exit 1
}

say "PJA110 baseline phase 2b  $(date -Is)"
[ "$(id -u)" = 0 ] || fail "run as root (sudo -i)"
apk info -e "device-oneplus-xigua=1-r7" >/dev/null || fail "device package 1-r7 is not installed"

UNITS="pja110-battmgr-readonly pja110-adc-test pja110-charger-capture \
pja110-wifi-probe pja110-wifi-clean-boot pja110-wifi-aston-rfkill"
ts=$(date +%Y%m%d-%H%M%S)
B=/var/lib/pja110-baseline/$ts-units
mkdir -p "$B/files"
: > "$B/files.txt"

say "backup: $B"
for u in $UNITS; do
    f=/etc/systemd/system/$u.service
    active=$(systemctl is-active "$u.service" 2>/dev/null || true)
    say "$u active=${active:-unknown}"
    if [ "$active" = "active" ] || [ "$active" = "activating" ]; then
        systemctl stop "$u.service" 2>/dev/null || true
    fi
    systemctl disable "$u.service" 2>/dev/null || true
    if [ -e "$f" ]; then
        mkdir -p "$B/files$(dirname "$f")"
        cp -a "$f" "$B/files$f"
        echo "$f" >> "$B/files.txt"
        rm -f "$f"
        say "removed $f"
    fi
    for w in /etc/systemd/system/*.wants/"$u.service"; do
        [ -e "$w" ] || [ -L "$w" ] || continue
        mkdir -p "$B/files$(dirname "$w")"
        cp -a "$w" "$B/files$w" 2>/dev/null || true
        echo "$w" >> "$B/files.txt"
        rm -f "$w"
        say "removed $w"
    done
done

systemctl daemon-reload

cat > "$B/restore.sh" <<EOF
#!/bin/sh
set -eu
cp -a "$B"/files/. /
systemctl daemon-reload
echo "Restored the temporary unit files. Run systemctl enable <unit> if needed."
EOF
chmod 700 "$B/restore.sh"
say "restore script: $B/restore.sh"

say ""
say "== migrate-baseline check =="
set +e
/usr/libexec/pja110-migrate-baseline check
rc=$?
set -e
[ "$rc" = 0 ] || fail "migrate check still failing (rc=$rc)"
chmod 644 "$LOG" 2>/dev/null || true
printf '\nPHASE2B_OK log: %s\nNext: rerun phase 3 as root:\n  sh %s/phase3-final-check.sh\n' "$LOG" "$D" >&3
trap - EXIT
