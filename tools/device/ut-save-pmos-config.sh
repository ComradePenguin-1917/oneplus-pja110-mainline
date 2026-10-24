#!/bin/sh
# Preserve the pmOS userland configuration before sda14 is wiped.
#
# This collects the pieces that are expensive or annoying to recreate, but are
# NOT part of the install image: SSH host and client keys, per-user config,
# systemd units that were hand-installed, the pja110 baseline transactions, the
# retained APK cache, and the pmOS package list.
#
# Output: /home/penguin/ut-backup/pmos-config-<timestamp>.tar.zst
#
#   sudo -i
#   sh /home/penguin/ut-test/ut-save-pmos-config.sh
set -eu
OUT=${OUT:-/home/penguin/ut-backup}
TS=$(date +%Y%m%d-%H%M%S)
STAGE=/tmp/pmos-config-$TS
LOG=/home/penguin/ut-test/ut-save-pmos-config-$TS.log
mkdir -p "$OUT" "$STAGE"
exec 3>&1 4>&2
exec >>"$LOG" 2>&1
say() { printf '%s\n' "$*"; }
fail() {
    say "FAIL: $*"
    chmod 644 "$LOG" 2>/dev/null || true
    { printf '\nUT_SAVECFG_FAILED: %s\nlog: %s\n' "$*" "$LOG"; tail -n 30 "$LOG"; } >&3
    exit 1
}

[ "$(id -u)" = 0 ] || fail "run as root (sudo -i)"

say "== collecting =="

# 1. SSH: host keys and the user's authorised/material keys
mkdir -p "$STAGE/ssh"
for f in /etc/ssh/ssh_host_* /etc/ssh/sshd_config; do
    [ -e "$f" ] && cp -a "$f" "$STAGE/ssh/" 2>/dev/null || true
done
[ -d /home/penguin/.ssh ] && cp -a /home/penguin/.ssh "$STAGE/ssh/user-ssh" 2>/dev/null || true
say "ssh: $(ls "$STAGE/ssh" | wc -l) entries"

# 2. User home configuration (skip caches)
mkdir -p "$STAGE/home"
for d in .config .local/share/phosh .local/share/gnome .bashrc .profile .zshrc; do
    if [ -e "/home/penguin/$d" ]; then
        mkdir -p "$STAGE/home/$(dirname "$d")"
        cp -a "/home/penguin/$d" "$STAGE/home/$d" 2>/dev/null || true
    fi
done
say "home entries: $(find "$STAGE/home" -mindepth 1 -maxdepth 1 | wc -l)"

# 3. Hand-installed units and the baseline transaction history
mkdir -p "$STAGE/systemd"
cp -a /etc/systemd/system "$STAGE/systemd/" 2>/dev/null || true
cp -a /var/lib/pja110-baseline "$STAGE/pja110-baseline" 2>/dev/null || true
say "systemd + baseline saved"

# 4. Kernel/device packages and the apk cache (so the old versions can be reinstalled)
mkdir -p "$STAGE/apk"
cp -a /var/cache/apk/*.apk "$STAGE/apk/" 2>/dev/null || true
say "cached apks: $(ls "$STAGE/apk" 2>/dev/null | wc -l)"

# 5. Package inventory and network/bluetooth identity
mkdir -p "$STAGE/meta"
apk info -v 2>/dev/null | sort > "$STAGE/meta/packages.txt" || true
cat /etc/os-release > "$STAGE/meta/os-release.txt" 2>/dev/null || true
uname -a > "$STAGE/meta/uname.txt" 2>/dev/null || true
for f in /etc/hostname /etc/hosts /etc/fstab /etc/resolv.conf; do
    cp -a "$f" "$STAGE/meta/" 2>/dev/null || true
done
mkdir -p "$STAGE/network"
for f in /etc/NetworkManager/system-connections/*; do
    [ -e "$f" ] && cp -a "$f" "$STAGE/network/" 2>/dev/null || true
done
say "meta saved; network profiles: $(ls "$STAGE/network" 2>/dev/null | wc -l)"

# 6. pja110 install directory (scripts, APKs, images uploaded earlier)
[ -d /home/penguin/pja110-install ] && cp -a /home/penguin/pja110-install "$STAGE/pja110-install" 2>/dev/null || true

say "== size before compression =="
du -sh "$STAGE" | tail -1

say "== compress =="
TARBALL=$OUT/pmos-config-$TS.tar.zst
if command -v zstd >/dev/null 2>&1; then
    tar -C "$STAGE" -cf - . | zstd -q -3 -o "$TARBALL" || fail "tar/zstd failed"
else
    TARBALL=$OUT/pmos-config-$TS.tar.gz
    tar -C "$STAGE" -czf "$TARBALL" . || fail "tar/gz failed"
fi
sync
say "archive: $TARBALL"
ls -lh "$TARBALL"
sha256sum "$TARBALL"

say "== contents summary =="
tar -tf "$TARBALL" | awk -F/ '{print $2}' | sort -u | head -20

rm -rf "$STAGE"
chmod 644 "$LOG" 2>/dev/null || true
printf '\nUT_SAVECFG_DONE archive=%s log=%s\n' "$TARBALL" "$LOG" >&3
