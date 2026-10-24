"""Produce the final boot chain and the one-shot installer.

Outputs:
  final-boot_a.img            kernel, cmdline without root= (initramfs decides)
  final-vendor_boot_a.img     minimal initramfs: wait for root, mount, switch_root
  install-boot_a.img          same kernel, used only to run the installer
  install-vendor_boot_a.img   ramdisk that copies the root and flashes both images

The minimal initramfs waits for the root device because UFS enumeration finishes
after the VFS tries root=; an empty initramfs fails with
"VFS: Unable to mount root fs on unknown-block(0,0)".
"""
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
UT_INIT = ROOT / 'ut-init.sh'
BOOT_SRC = OUT / 'boot-ut' / 'boot_a.img'


def cpio_with(files):
    """Build a newc archive with the alignment the kernel expects.

    Each entry's header+name+data must be padded to 4 bytes, and the archive ends
    with TRAILER!!! followed by zero padding. Without this the kernel stops
    parsing and reports "No working init found".
    """
    out = bytearray()
    ino = 1
    for name, data, mode in files:
        fields = [ino, mode, 0, 0, 1, 0, len(data), 0, 0, 0, 0, 0, 0]
        entry = make_entry(fields, name, data)
        out += entry
        while len(out) % 4:
            out.append(0)
        ino += 1
    header = make_entry([ino, 0o040755, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0],
                        'TRAILER!!!', b'')
    out += header
    while len(out) % 512:
        out.append(0)
    return bytes(out)


def ramdisk(files):
    archive = cpio_with(files)
    names = [n for _, n, _ in parse_cpio(archive)]
    rd = lz4(['-z', '-l', '-12', '-c'], archive)
    return archive, rd, names


def build_vendor(rd, target):
    vendor = DEFAULT_VENDOR.read_bytes()
    assert vendor[:8] == b'VNDRBOOT'
    rdsize = struct.unpack_from('<I', vendor, 24)[0]
    hsize, dsize = struct.unpack_from('<II', vendor, 2096)
    rdoff = align(hsize)
    dtboff = align(rdoff + rdsize)
    tableoff = align(dtboff + dsize)
    tail = avb_offset(vendor)
    assert len(rd) <= rdsize, f'ramdisk {len(rd)} > fragment {rdsize}'
    out = bytearray(vendor)
    out[rdoff:rdoff + rdsize] = rd + bytes(rdsize - len(rd))
    assert out[rdoff + rdsize:dtboff] == vendor[rdoff + rdsize:dtboff]
    assert out[dtboff:tableoff] == vendor[dtboff:tableoff]
    assert out[tableoff:tail] == vendor[tableoff:tail]
    assert out[tail:] == vendor[tail:]
    assert FDT(out[dtboff:dtboff + dsize]).nodes()['/']['compatible'] \
        .split(b'\0')[:2] == [b'oneplus,xigua', b'qcom,sm8550']
    target.write_bytes(bytes(out))
    return rdsize


def cmdline_boot(cmd: bytes, target):
    data = bytearray(BOOT_SRC.read_bytes())
    assert len(cmd) < 512
    data[44:44 + 512] = cmd + b'\x00' * (512 - len(cmd))
    target.write_bytes(bytes(data))


def main():
    for p in (BUSYBOX, LOADER, UT_INIT, BOOT_SRC):
        assert p.is_file(), p

    busy = BUSYBOX.read_bytes()
    loader = LOADER.read_bytes()
    init = UT_INIT.read_bytes()

    # 1. minimal initramfs for the real boot
    archive, rd, names = ramdisk([
        ('bin', b'', 0o040755),
        ('bin/busybox', busy, 0o100755),
        ('lib', b'', 0o040755),
        ('lib/ld-musl-aarch64.so.1', loader, 0o100755),
        ('lib/libc.musl-aarch64.so.1', loader, 0o100755),
        ('init', init, 0o100755),
    ])
    assert 'init' in names
    frag = build_vendor(rd, OUT / 'final-vendor_boot_a.img')

    # 2. final boot image: no root=, the initramfs finds it
    cmdline_boot(b'console=ttyMSM0,115200n8 loglevel=6 '
                 b'panel_oneplus_aa536.refresh=120',
                 OUT / 'final-boot_a.img')

    # 3. installer ramdisk embeds both final images
    final_boot = (OUT / 'final-boot_a.img').read_bytes()
    final_vendor = (OUT / 'final-vendor_boot_a.img').read_bytes()
    inst_init = (ROOT / 'ut-install-init.sh').read_bytes()
    archive2, rd2, names2 = ramdisk([
        ('bin', b'', 0o040755),
        ('bin/busybox', busy, 0o100755),
        ('lib', b'', 0o040755),
        ('lib/ld-musl-aarch64.so.1', loader, 0o100755),
        ('lib/libc.musl-aarch64.so.1', loader, 0o100755),
        ('init', inst_init, 0o100755),
    ])
    assert 'init' in names2
    build_vendor(rd2, OUT / 'install-vendor_boot_a.img')
    cmdline_boot(b'console=ttyMSM0,115200n8 loglevel=6', OUT / 'install-boot_a.img')

    manifest = {
        'final_boot': {'path': str(OUT / 'final-boot_a.img'),
                       'bytes': (OUT / 'final-boot_a.img').stat().st_size,
                       'sha256': sha((OUT / 'final-boot_a.img').read_bytes())},
        'final_vendor': {'path': str(OUT / 'final-vendor_boot_a.img'),
                         'bytes': (OUT / 'final-vendor_boot_a.img').stat().st_size,
                         'sha256': sha((OUT / 'final-vendor_boot_a.img').read_bytes())},
        'install_boot': {'path': str(OUT / 'install-boot_a.img'),
                         'bytes': (OUT / 'install-boot_a.img').stat().st_size,
                         'sha256': sha((OUT / 'install-boot_a.img').read_bytes())},
        'install_vendor': {'path': str(OUT / 'install-vendor_boot_a.img'),
                           'bytes': (OUT / 'install-vendor_boot_a.img').stat().st_size,
                           'sha256': sha((OUT / 'install-vendor_boot_a.img').read_bytes())},
        'initramfs': {'compressed': len(rd), 'uncompressed': len(archive),
                      'fragment': frag},
    }
    (OUT / 'final-chain-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps(manifest, indent=2))
    print('PASS: final boot chain and installer built')


if __name__ == '__main__':
    main()
