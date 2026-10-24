"""Build a rescue vendor_boot whose ramdisk dd's the UT root from super to sda14.

Why this shape:
  - the UT root already exists as a complete ext4 image on /dev/sda6 (super)
  - copying it raw to /dev/sda14 puts the same filesystem at offset 0, so the
    kernel can mount it with the very same root=UUID, no partitioning needed
  - the rescue system therefore only needs busybox: dd, sync, reboot

The ramdisk is a static busybox plus a small /init; it replaces the vendor
fragment of the verified container and keeps the DTB and AVB tail untouched.
"""
import io
import json
import struct
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from build_native_slot_image import (DEFAULT_VENDOR, align, avb_offset, lz4,
                                     make_entry, parse_cpio, sha)
from fdt import FDT

OUT = ROOT / 'out/ut-test'
RESCUE = ROOT / 'out/ut-test/rescue-bin'
BUSYBOX = RESCUE / 'busybox'
LOADER = RESCUE / 'ld-musl-aarch64.so.1'

INIT = b'''#!/bin/busybox sh
/bin/busybox --install -s
mount -t proc proc /proc 2>/dev/null
mount -t sysfs sys /sys 2>/dev/null
mount -t devtmpfs dev /dev 2>/dev/null

echo "=============================================="
echo " PJA110 rescue: copy UT root from super to sda14"
echo "=============================================="

# Wait for both block devices to settle.
i=0
while [ $i -lt 40 ]; do
    [ -b /dev/sda6 ] && [ -b /dev/sda14 ] && break
    i=$((i+1))
    sleep 1
done

if [ ! -b /dev/sda6 ] || [ ! -b /dev/sda14 ]; then
    echo "ERROR: sda6/sda14 not present; dropping to shell"
    exec /bin/sh
fi

echo "source: /dev/sda6"
echo "target: /dev/sda14 (about to be overwritten)"
echo "copying, this takes a few minutes..."
dd if=/dev/sda6 of=/dev/sda14 bs=1M conv=fsync 2>&1 | tail -3
sync
echo "=============================================="
echo " copy finished; rebooting to boot the UT root"
echo "=============================================="
sleep 3
reboot -f
exec /bin/sh
'''


def cpio_with(files):
    """files: list of (name, data, mode) -> newc archive bytes."""
    out = bytearray()
    ino = 1
    for name, data, mode in files:
        fields = [ino, mode, 0, 0, 1, 0, len(data), 0, 0, 0, 0, 0, 0]
        out += make_entry(fields, name, data)
        ino += 1
    out += make_entry([ino, 0o040755, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0],
                      'TRAILER!!!', b'')
    return bytes(out)


def main():
    assert BUSYBOX.is_file(), BUSYBOX
    assert LOADER.is_file(), LOADER
    busy = BUSYBOX.read_bytes()
    loader = LOADER.read_bytes()
    init = INIT
    archive = cpio_with([
        ('bin', b'', 0o040755),
        ('bin/busybox', busy, 0o100755),
        ('lib', b'', 0o040755),
        ('lib/ld-musl-aarch64.so.1', loader, 0o100755),
        ('lib/libc.musl-aarch64.so.1', loader, 0o100755),
        ('init', init, 0o100755),
    ])
    # sanity: the archive must list our init
    names = [n for _, n, _ in parse_cpio(archive)]
    assert './init' in names or 'init' in names, names[:5]
    rd = lz4(['-z', '-l', '-12', '-c'], archive)

    vendor = DEFAULT_VENDOR.read_bytes()
    assert vendor[:8] == b'VNDRBOOT'
    rdsize = struct.unpack_from('<I', vendor, 24)[0]
    hsize, dsize = struct.unpack_from('<II', vendor, 2096)
    rdoff = align(hsize)
    dtboff = align(rdoff + rdsize)
    tableoff = align(dtboff + dsize)
    vendor_tail = avb_offset(vendor)
    assert len(rd) <= rdsize, f'ramdisk {len(rd)} > {rdsize}'

    out = bytearray(vendor)
    out[rdoff:rdoff + rdsize] = rd + bytes(rdsize - len(rd))
    # DTB, ramdisk table, bootconfig and AVB tail must stay byte-identical.
    assert out[rdoff + rdsize:dtboff] == vendor[rdoff + rdsize:dtboff]
    assert out[dtboff:tableoff] == vendor[dtboff:tableoff]
    assert out[tableoff:vendor_tail] == vendor[tableoff:vendor_tail]
    assert out[vendor_tail:] == vendor[vendor_tail:]
    # The DTB inside must still describe this device.
    assert FDT(out[dtboff:dtboff + dsize]).nodes()['/']['compatible'] \
        .split(b'\0')[:2] == [b'oneplus,xigua', b'qcom,sm8550']

    OUT.mkdir(parents=True, exist_ok=True)
    target = OUT / 'vendor_boot_a-rescue.img'
    target.write_bytes(bytes(out))
    manifest = {
        'purpose': 'rescue ramdisk: dd UT root from /dev/sda6 to /dev/sda14',
        'ramdisk': {'bytes': len(rd), 'uncompressed': len(archive),
                    'sha256': sha(rd)},
        'inputs': {'busybox': {'path': str(BUSYBOX), 'bytes': len(busy),
                               'sha256': sha(busy)},
                   'loader': {'path': str(LOADER), 'bytes': len(loader),
                              'sha256': sha(loader)},
                   'template': {'path': str(DEFAULT_VENDOR),
                                'sha256': sha(vendor)}},
        'output': {'path': str(target), 'bytes': target.stat().st_size,
                   'sha256': sha(target.read_bytes())},
        'dtb_unchanged': True,
    }
    (OUT / 'rescue-vendor-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps(manifest, indent=2))
    print('PASS: rescue vendor_boot built')


if __name__ == '__main__':
    main()
