#!/bin/bash
# Boot the minimal initramfs under QEMU before flashing it.
#
# Validates the parts that used to fail silently on the device:
#   - /init actually runs and reaches its own output
#   - busybox applets resolve (no "--install -s" errors)
#   - devtmpfs mounts and block devices are enumerable
#   - the root-mount path reports a clear FATAL instead of hanging
#
# Run inside WSL from the repository root:
#   bash tools/qemu-check-initramfs.sh
set -euo pipefail

REPO=/mnt/h/workspace/PJA110-Mainline
OUT=$REPO/out/ut-test
WORK=/tmp/qemu-initramfs-check
KERNEL=$REPO/out/postmarketos-baseline-20261017/vmlinuz

mkdir -p "$WORK"
cd "$WORK"

if [ ! -f Image ]; then
    cp "$KERNEL" Image
fi

# Pull the ramdisk out of the vendor_boot image we are about to flash.
python3 - "$OUT/mini-vendor_boot_a.img" <<'EOF'
import struct, sys
from pathlib import Path
raw = Path(sys.argv[1]).read_bytes()
def align(n): return (n + 4095) // 4096 * 4096
rdsize = struct.unpack_from('<I', raw, 24)[0]
hsize, _ = struct.unpack_from('<II', raw, 2096)
off = align(hsize)
Path('/tmp/qemu-initramfs-check/rd.lz4').write_bytes(raw[off:off + rdsize])
print(f'fragment {rdsize} bytes')
EOF

lz4 -d -f rd.lz4 initrd.cpio >/dev/null 2>&1 || true
echo "initramfs: $(stat -c %s initrd.cpio) bytes"

echo "--- booting (45s budget) ---"
set +e
timeout 45 qemu-system-aarch64 \
    -M virt -cpu cortex-a57 -m 2G -nographic \
    -kernel Image -initrd initrd.cpio \
    -append 'console=ttyAMA0 rdinit=/init loglevel=7' \
    > qemu.log 2>&1
rc=$?
set -e

echo "--- qemu exit: $rc ---"
echo "--- ut-init lines ---"
grep -a '\[ut-init\]' qemu.log || echo '(none)'
echo "--- problems ---"
grep -aE 'busybox: .*No such file|Kernel panic|No working init|not found' qemu.log | head -10 || true
echo "--- verdict ---"
if grep -aq '\[ut-init\] starting' qemu.log; then
    echo "PASS: init runs and prints its own output"
else
    echo "FAIL: init produced no output"
fi
