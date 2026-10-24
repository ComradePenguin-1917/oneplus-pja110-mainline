"""Build a self-contained rescue that finishes the whole Option B install.

The rescue ramdisk:
  1. dd /dev/sda6 (UT root, ext4, from the earlier stage) -> /dev/sda14
  2. writes the provided boot_a and vendor_boot_a into their partitions
  3. reboots; the device then boots straight into Ubuntu Touch

Inputs (all produced here):
  rescue ramdisk   busybox + musl loader + /init + the two images to flash
  boot image       kernel + cmdline with no root= (initramfs drives everything)

Flash images are embedded in the ramdisk because fastboot cannot write while the
ramdisk runs; total ramdisk stays far below the 16.7 MiB vendor fragment.
"""
import io
import json
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from build_native_slot_image import (DEFAULT_VENDOR, align, avb_offset, lz4,
                                     make_entry, parse_cpio, sha)
from fdt import FDT

OUT = ROOT / 'out/ut-test'
RESCUE = OUT / 'rescue-bin'
BUSYBOX = RESCUE / 'busybox'
LOADER = RESCUE / 'ld-musl-aarch64.so.1'

# Images the rescue writes back into the boot partitions before rebooting.
NEW_BOOT = OUT / 'final-boot_a.img'
NEW_VENDOR = OUT / 'final-vendor_boot_a.img'

INIT = b'''#!/bin/busybox sh
/bin/busybox --install -s
mount -t proc proc /proc 2>/dev/null
mount -t sysfs sys /sys 2>/dev/null
mount -t devtmpfs dev /dev 2>/dev/null

echo "==================================================="
echo " PJA110 Ubuntu Touch install (Option B, final)"
echo "==================================================="

i=0
while [ $i -lt 60 ]; do
    [ -b /dev/sda6 ] && [ -b /dev/sda14 ] && [ -b /dev/disk/by-partlabel/boot_a ] \
        && [ -b /dev/disk/by-partlabel/vendor_boot_a ] && break
    i=$((i+1)); sleep 1
done

for d in /dev/sda6 /dev/sda14 /dev/disk/by-partlabel/boot_a /dev/disk/by-partlabel/vendor_boot_a; do
    if [ ! -b "$d" ]; then echo "FATAL: $d missing"; exec /bin/sh; fi
done

echo "[1/3] copying root filesystem to /dev/sda14"
dd if=/dev/sda6 of=/dev/sda14 bs=1M conv=fsync 2>&1 | tail -2
sync

echo "[2/3] writing boot images"
dd if=/flash/boot_a.img of=/dev/disk/by-partlabel/boot_a bs=1M conv=fsync 2>&1 | tail -1
sync
dd if=/flash/vendor_boot_a.img of=/dev/disk/by-partlabel/vendor_boot_a bs=1M conv=fsync 2>&1 | tail -1
sync

echo "[3/3] verifying boot_a read-back"
a=$(sha256sum /dev/disk/by-partlabel/boot_a | cut -d' ' -f1)
w=$(sha256sum /flash/boot_a.img | cut -d' ' -f1)
echo "boot_a now: $a"
if [ "$a" = "$w" ]; then echo "boot_a OK"; else echo "boot_a MISMATCH"; fi
v=$(sha256sum /dev/disk/by-partlabel/vendor_boot_a | cut -d' ' -f1)
wv=$(sha256sum /flash/vendor_boot_a.img | cut -d' ' -f1)
echo "vendor_boot_a now: $v"
if [ "$v" = "$wv" ]; then echo "vendor_boot_a OK"; else echo "vendor_boot_a MISMATCH"; fi

echo "==================================================="
echo " done; rebooting into Ubuntu Touch"
echo "==================================================="
sleep 5
reboot -f
exec /bin/sh
'''


def cpio_with(files):
    out = bytearray()
    ino = 1
    for name, data, mode in files:
        fields = [ino, mode, 0, 0, 1, 0, len(data), 0, 0, 0, 0, 0, 0]
        out += make_entry(fields, name, data)
        ino += 1
    out += make_entry([ino, 0o040755, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0],
                      'TRAILER!!!', b'')
    return bytes(out)


def build_vendor(ramdisk, source, target):
    vendor = source.read_bytes()
    assert vendor[:8] == b'VNDRBOOT'
    rdsize = struct.unpack_from('<I', vendor, 24)[0]
    hsize, dsize = struct.unpack_from('<II', vendor, 2096)
    rdoff = align(hsize)
    dtboff = align(rdoff + rdsize)
    tableoff = align(dtboff + dsize)
    tail = avb_offset(vendor)
    assert len(ramdisk) <= rdsize, f'ramdisk {len(ramdisk)} > fragment {rdsize}'
    out = bytearray(vendor)
    out[rdoff:rdoff + rdsize] = ramdisk + bytes(rdsize - len(ramdisk))
    assert out[rdoff + rdsize:dtboff] == vendor[rdoff + rdsize:dtboff]
    assert out[dtboff:tableoff] == vendor[dtboff:tableoff]
    assert out[tableoff:tail] == vendor[tableoff:tail]
    assert out[tail:] == vendor[tail:]
    assert FDT(out[dtboff:dtboff + dsize]).nodes()['/']['compatible'] \
        .split(b'\0')[:2] == [b'oneplus,xigua', b'qcom,sm8550']
    target.write_bytes(bytes(out))
    return rdsize, tail


def main():
    for p in (BUSYBOX, LOADER, NEW_BOOT, NEW_VENDOR):
        assert p.is_file(), p

    busy = BUSYBOX.read_bytes()
    loader = LOADER.read_bytes()
    boot = NEW_BOOT.read_bytes()
    vendor_final = NEW_VENDOR.read_bytes()

    # ramdisk carries the images to flash
    archive = cpio_with([
        ('bin', b'', 0o040755),
        ('bin/busybox', busy, 0o100755),
        ('lib', b'', 0o040755),
        ('lib/ld-musl-aarch64.so.1', loader, 0o100755),
        ('lib/libc.musl-aarch64.so.1', loader, 0o100755),
        ('flash', b'', 0o040755),
        ('flash/boot_a.img', boot, 0o100644),
        ('flash/vendor_boot_a.img', vendor_final, 0o100644),
        ('init', INIT, 0o100755),
    ])
    names = [n for _, n, _ in parse_cpio(archive)]
    assert './init' in names and './flash/boot_a.img' in names, names[:8]
    rd = lz4(['-z', '-l', '-12', '-c'], archive)

    rdsize, tail = build_vendor(rd, DEFAULT_VENDOR, OUT / 'install-vendor_boot_a.img')

    # boot image: same kernel, cmdline without root= so /init runs
    src_boot = bytearray((OUT / 'boot-ut' / 'boot_a.img').read_bytes())
    cmd = b'console=ttyMSM0,115200n8 loglevel=6 panel_oneplus_aa536.refresh=120'
    src_boot[44:44 + 512] = cmd + b'\x00' * (512 - len(cmd))
    (OUT / 'install-boot_a.img').write_bytes(bytes(src_boot))

    manifest = {
        'purpose': 'one-shot Option B install: copy UT root, flash boot images, reboot',
        'ramdisk': {'compressed': len(rd), 'uncompressed': len(archive),
                    'sha256': sha(rd)},
        'embedded': {
            'boot_a': {'bytes': len(boot), 'sha256': sha(boot)},
            'vendor_boot_a': {'bytes': len(vendor_final), 'sha256': sha(vendor_final)},
        },
        'vendor_fragment': rdsize,
        'files': {
            'boot': str(OUT / 'install-boot_a.img'),
            'vendor': str(OUT / 'install-vendor_boot_a.img'),
        },
    }
    (OUT / 'install-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps(manifest, indent=2))
    print('PASS: install rescue built')


if __name__ == '__main__':
    main()
