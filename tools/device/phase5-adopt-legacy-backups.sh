#!/bin/sh
# PJA110 baseline, phase 5: adopt the pre-transaction backups written by the
# first upgrade run into typed transactions, so `restore --list/--tx` covers the
# current device as well.
#
#   sudo -i
#   sh /home/penguin/pja110-install/phase5-adopt-legacy-backups.sh
#
# Read-only with respect to the running system: it only creates transaction
# directories under /var/lib/pja110-baseline/transactions/ from the existing
# backup directories and the retained APK cache.
set -eu
STATE=/var/lib/pja110-baseline
TX=$STATE/transactions
LOG=/home/penguin/pja110-install/phase5-$(date +%Y%m%d-%H%M%S).log
exec 3>&1 4>&2
exec >>"$LOG" 2>&1
say() { printf '%s\n' "$*"; }
fail() {
    say "FAIL: $*"
    chmod 644 "$LOG" 2>/dev/null || true
    { printf '\nPHASE5_FAILED: %s\nfull log: %s\n' "$*" "$LOG"; tail -n 30 "$LOG"; } >&3
    exit 1
}

say "PJA110 baseline phase 5  $(date -Is)"
[ "$(id -u)" = 0 ] || fail "run as root (sudo -i)"
mkdir -p "$TX"

adopt_install() {
    src=$STATE/20261017-213025
    id=install-adopted-20261017-213025
    dst=$TX/$id
    [ -d "$src" ] || fail "missing $src"
    [ -d "$dst" ] && { say "already adopted: $id"; return 0; }
    mkdir -p "$dst/partitions" "$dst/apks"
    for p in boot_a vendor_boot_a init_boot_a dtbo_a; do
        [ -f "$src/$p.img" ] || fail "missing $src/$p.img"
        cp -a "$src/$p.img" "$dst/partitions/$p.img"
    done
    sha256sum "$dst"/partitions/*.img > "$dst/SHA256SUMS"
    [ -f "$src/legacy-usr-local.tar" ] && cp -a "$src/legacy-usr-local.tar" "$dst/files.tar"
    cp -a "$src/slot-b-before.txt" "$dst/"
    awk '$2 == "enabled" && $1 ~ /^pja110-/ {print $1}' "$src/units-before.txt" > "$dst/units" || true
    apks=""
    for spec in "linux-oneplus-xigua-6.14-r1" "device-oneplus-xigua-1-r4"; do
        cached=$(ls /var/cache/apk/"$spec".*.apk 2>/dev/null | head -n 1 || true)
        if [ -n "$cached" ]; then
            cp -a "$cached" "$dst/apks/$spec.apk"
            apks="$apks${apks:+,}$spec.apk"
        fi
    done
    {
        echo "id=$id"
        echo "kind=install"
        echo "created=$(date -Is)"
        echo "partitions=boot_a,vendor_boot_a,init_boot_a,dtbo_a"
        echo "files=files.tar"
        echo "units=units"
        echo "apks=$apks"
        echo "status=adopted"
        echo "note=adopted from the first upgrade run; files.tar contains only the legacy /usr/local tree, the old kernel/device packages come from the retained APK cache"
    } > "$dst/meta"
    say "adopted $id (apks: ${apks:-none})"
}

adopt_tree() {
    src=$1
    id=$2
    kind=$3
    dst=$TX/$id
    [ -d "$src" ] || fail "missing $src"
    [ -d "$dst" ] && { say "already adopted: $id"; return 0; }
    mkdir -p "$dst"
    cp -a "$src/files" "$dst/files"
    cp -a "$src/files.txt" "$dst/files.txt" 2>/dev/null || true
    if [ -f "$src/units.txt" ]; then
        cp -a "$src/units.txt" "$dst/units"
    else
        : > "$dst/units"
    fi
    {
        echo "id=$id"
        echo "kind=$kind"
        echo "created=$(date -Is)"
        echo "partitions="
        echo "files=files"
        echo "units=units"
        echo "apks="
        echo "status=adopted"
        echo "note=adopted from ${src##*/}; restores only the files it originally backed up"
    } > "$dst/meta"
    say "adopted $id"
}

adopt_install
adopt_tree "$STATE/20261017-213413" migration-adopted-20261017-213413 migration
adopt_tree "$STATE/20261017-213801-units" units-adopted-20261017-213801 units

say ""
say "== transactions =="
/usr/libexec/pja110-migrate-baseline restore --list

say ""
say "== dry-run of the adopted install transaction =="
/usr/libexec/pja110-migrate-baseline restore --tx install-adopted-20261017-213025 --dry-run

chmod 644 "$LOG" 2>/dev/null || true
printf '\nPHASE5_OK log: %s\nRollback is now: pja110-migrate-baseline restore --list\n                 pja110-migrate-baseline restore --tx <id>\n' "$LOG" >&3
trap - EXIT
