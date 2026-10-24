#!/bin/bash
# Offline rehearsal of the migration restore selection and partial rollback.
# Runs against a temporary fake state/root; never touches the phone or /.
#
#   sudo bash tools/rehearse_rollback.sh
#
# Exercises:
#   * restore without --tx refuses and lists transactions (no "latest" guessing)
#   * restore --list shows kind/status/partitions
#   * --dry-run validates and prints, writing nothing
#   * unknown transaction id is rejected
#   * a partial install transaction restores only the partitions it contains
#   * a full install transaction restores partitions and files.tar
#   * a migration transaction restores its file tree
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
SCRIPT=$ROOT/postmarketos/device/testing/device-oneplus-xigua/pja110-migrate-baseline.sh
LOG=$ROOT/out/deepseek-review-20261017/rollback-rehearsal.log
mkdir -p "$(dirname "$LOG")"
exec > >(tee "$LOG") 2>&1

TMP=$(mktemp -d /tmp/pja110-rehearsal.XXXXXX)
trap 'rm -rf "$TMP"' EXIT
export PJA110_STATE=$TMP/state
export PJA110_ROOT=$TMP/root
mkdir -p "$PJA110_ROOT/dev/disk/by-partlabel" "$PJA110_STATE/transactions"

fail() { echo "REHEARSAL_FAIL: $*"; exit 1; }
run() { echo "+ pja110-migrate-baseline $*"; sh "$SCRIPT" "$@"; }

make_partition() { # path size_kb
    head -c $(( $2 * 1024 )) /dev/urandom > "$1"
}

# --- transaction A: full install backup ------------------------------------
A=$PJA110_STATE/transactions/install-20260101-000001
mkdir -p "$A/partitions" "$A/files"
mkdir -p "$TMP/filesrc/boot" "$TMP/filesrc/lib/modules/6.14.0-oneplus-xigua"
echo "old-kernel" > "$TMP/filesrc/boot/vmlinuz"
echo "old-module" > "$TMP/filesrc/lib/modules/6.14.0-oneplus-xigua/qcom_battmgr.ko"
tar -C "$TMP/filesrc" -cf "$A/files.tar" .
make_partition "$A/partitions/boot_a.img" 64
make_partition "$A/partitions/vendor_boot_a.img" 64
cat > "$A/meta" <<'EOF'
id=install-20260101-000001
kind=install
created=2026-01-01T00:00:01+08:00
partitions=boot_a,vendor_boot_a
files=files.tar
units=units
status=partial
EOF
: > "$A/units"

# --- transaction B: migration-only -----------------------------------------
B=$PJA110_STATE/transactions/migration-20260101-000002
mkdir -p "$B/files/usr/local/libexec" "$B/files/etc/systemd/system"
echo "legacy-script" > "$B/files/usr/local/libexec/pja110-mark-a-success"
echo "legacy-unit" > "$B/files/etc/systemd/system/pja110-adc-test.service"
printf 'pja110-adc-test.service\n' > "$B/units"
cat > "$B/meta" <<'EOF'
id=migration-20260101-000002
kind=migration
created=2026-01-01T00:00:02+08:00
partitions=
files=files
units=units
status=complete
EOF

# --- transaction C: partial write (boot_a only) ----------------------------
C=$PJA110_STATE/transactions/install-20260101-000003
mkdir -p "$C/partitions"
make_partition "$C/partitions/boot_a.img" 64
cat > "$C/meta" <<'EOF'
id=install-20260101-000003
kind=install
created=2026-01-01T00:00:03+08:00
partitions=boot_a
files=
units=
status=partial
EOF

# fake current partitions
make_partition "$PJA110_ROOT/dev/disk/by-partlabel/boot_a" 64
make_partition "$PJA110_ROOT/dev/disk/by-partlabel/vendor_boot_a" 64

echo "== 1. restore without --tx must refuse and list =="
set +e
out=$(run restore 2>&1); rc=$?
set -e
echo "$out"
[ $rc -ne 0 ] || fail "restore without --tx should fail"
echo "$out" | grep -q 'install-20260101-000001' || fail "list missing install tx"
echo "$out" | grep -q 'migration-20260101-000002' || fail "list missing migration tx"
echo "$out" | grep -q 'choose a transaction id' || fail "no explicit guidance"

echo "== 2. restore --list shows kind/status/partitions =="
out=$(run restore --list)
echo "$out"
echo "$out" | grep -q 'kind=install' || fail "kind not shown"
echo "$out" | grep -q 'partitions=boot_a,vendor_boot_a' || fail "partitions not shown"
echo "$out" | grep -q 'status=partial' || fail "status not shown"

echo "== 3. dry-run writes nothing =="
before=$(sha256sum "$PJA110_ROOT/dev/disk/by-partlabel/boot_a" | cut -d' ' -f1)
out=$(run restore --tx install-20260101-000003 --dry-run)
echo "$out"
after=$(sha256sum "$PJA110_ROOT/dev/disk/by-partlabel/boot_a" | cut -d' ' -f1)
[ "$before" = "$after" ] || fail "dry-run wrote boot_a"
echo "$out" | grep -q 'dry-run complete; nothing written' || fail "dry-run note missing"

echo "== 4. migration dry-run mentions file tree and units =="
out=$(run restore --tx migration-20260101-000002 --dry-run)
echo "$out"
echo "$out" | grep -q 'would copy' || fail "file tree not mentioned"
echo "$out" | grep -q 'pja110-adc-test.service' || fail "units not mentioned"

echo "== 5. unknown transaction rejected =="
set +e
out=$(run restore --tx does-not-exist 2>&1); rc=$?
set -e
echo "$out"
[ $rc -ne 0 ] || fail "unknown tx should fail"

echo "== 6. partial install restores only boot_a, verified =="
want=$(sha256sum "$C/partitions/boot_a.img" | cut -d' ' -f1)
run restore --tx install-20260101-000003
got=$(sha256sum "$PJA110_ROOT/dev/disk/by-partlabel/boot_a" | cut -d' ' -f1)
[ "$want" = "$got" ] || fail "boot_a not restored"

echo "== 7. full install restores partitions and files.tar =="
run restore --tx install-20260101-000001
want_boot=$(sha256sum "$A/partitions/boot_a.img" | cut -d' ' -f1)
got_boot=$(sha256sum "$PJA110_ROOT/dev/disk/by-partlabel/boot_a" | cut -d' ' -f1)
[ "$want_boot" = "$got_boot" ] || fail "boot_a full restore mismatch"
[ "$(cat "$PJA110_ROOT/lib/modules/6.14.0-oneplus-xigua/qcom_battmgr.ko")" = old-module ] ||
    fail "files.tar not restored"

echo "== 8. migration restores file tree =="
mkdir -p "$PJA110_ROOT/etc/systemd/system"
run restore --tx migration-20260101-000002
[ "$(cat "$PJA110_ROOT/usr/local/libexec/pja110-mark-a-success")" = legacy-script ] ||
    fail "legacy script not restored"
[ "$(cat "$PJA110_ROOT/etc/systemd/system/pja110-adc-test.service")" = legacy-unit ] ||
    fail "legacy unit not restored"

# --- transaction D: adopted install with old APKs --------------------------
D=$PJA110_STATE/transactions/install-adopted-20260101-000004
mkdir -p "$D/partitions" "$D/apks"
make_partition "$D/partitions/boot_a.img" 64
echo fake-old-kernel > "$D/apks/linux-oneplus-xigua-6.14-r1.apk"
: > "$D/units"
cat > "$D/meta" <<'EOF'
id=install-adopted-20260101-000004
kind=install
created=2026-01-01T00:00:04+08:00
partitions=boot_a
files=
units=units
apks=linux-oneplus-xigua-6.14-r1.apk
status=adopted
EOF

echo "== 9. adopted install dry-run lists old APKs =="
out=$(run restore --tx install-adopted-20260101-000004 --dry-run)
echo "$out"
echo "$out" | grep -q 'would install old package' || fail "old APK not mentioned"
echo "$out" | grep -q 'linux-oneplus-xigua-6.14-r1.apk' || fail "old APK name missing"

echo "== 10. missing old APK is rejected before writing =="
rm -f "$D/apks/linux-oneplus-xigua-6.14-r1.apk"
set +e
out=$(run restore --tx install-adopted-20260101-000004 --dry-run 2>&1); rc=$?
set -e
echo "$out"
[ $rc -ne 0 ] || fail "missing APK should fail"
echo "$out" | grep -q 'missing' || fail "missing APK not reported"

echo "PASS: rollback selection, dry-run and partial restore behave as designed"
