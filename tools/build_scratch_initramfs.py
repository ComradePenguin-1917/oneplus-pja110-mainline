"""Build a from-scratch Ubuntu Touch initramfs and slot-A boot chain.

No pmOS tree, no hand-rolled loader layout: a single statically linked busybox
plus /init. That removes every earlier failure mode (missing interpreter, musl
loader path, cpio alignment).

Outputs:
  out/ut-test/scratch-vendor_boot_a.img   vendor ramdisk = our initramfs
  out/ut-test/scratch-boot_a.img          kernel, root=UUID + console=tty0
  out/ut-test/scratch-init_boot_a.img     empty generic ramdisk

Run in WSL (ASCII-only on Windows; lz4 comes from the distro package).
"""
import json
import struct
import sys
from pathlib import Path

ROOT = Path('/mnt/h/workspace/PJA110-Mainline')
sys.path.insert(0, str(ROOT / 'tools'))
from build_native_slot_image import align, avb_offset, sha      # noqa: E402
from build_init_marker_test import make_entry, parse_cpio        # noqa: E402
from build_ut_vendor_wsl import lz4                              # noqa: E402
from fdt import FDT                                             # noqa: E402

OUT = ROOT / 'out/ut-test'
BUSYBOX = OUT / 'rescue-bin/busybox-static'
INIT = ROOT / 'ut-init.sh'
TEMPLATE_VENDOR = ROOT / 'out/ut-backup/backup-20261018-160329/vendor_boot_a.img'
TEMPLATE_BOOT = OUT / 'boot-direct/boot_a.img'
ROOT_UUID = '8c04e46c-5d09-42c5-bccf-5e20d49a17ff'


def cpio(files):
    out = bytearray()
    ino = 1
    for name, data, mode in files:
        fields = [ino, mode, 0, 0, 1, 0, len(data), 0, 0, 0, 0, 0, 0]
        out += make_entry(fields, name, data)
        ino += 1
    out += make_entry([ino, 0o040755, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0],
                      'TRAILER!!!', b'')
    while len(out) % 512:
        out.append(0)
    return bytes(out)


def main():
    busy = BUSYBOX.read_bytes()
    init = INIT.read_bytes()
    archive = cpio([
        ('dev', b'', 0o040755),
        ('proc', b'', 0o040755),
        ('sys', b'', 0o040755),
        ('tmp', b'', 0o041777),
        ('newroot', b'', 0o040755),
        ('bin', b'', 0o040755),
        ('bin/busybox', busy, 0o100755),
        ('init', init, 0o100755),
    ])
    names = [n for _, n, _ in parse_cpio(archive)]
    assert 'init' in names and 'bin/busybox' in names, names
    rd = lz4(['-z', '-l', '-12', '-f'], archive)

    vendor = bytearray(TEMPLATE_VENDOR.read_bytes())
    rdsize = struct.unpack_from('<I', vendor, 24)[0]
    hsize, dsize = struct.unpack_from('<II', vendor, 2096)
    rdoff = align(hsize)
    dtboff = align(rdoff + rdsize)
    tail = avb_offset(vendor)
    assert len(rd) <= rdsize, f'ramdisk {len(rd)} > fragment {rdsize}'
    vendor[rdoff:rdoff + rdsize] = rd + bytes(rdsize - len(rd))
    assert vendor[dtboff:tail] == bytes(TEMPLATE_VENDOR.read_bytes()[dtboff:tail]), \
        'DTB or vendor table changed'
    assert FDT(bytes(vendor[dtboff:dtboff + dsize])).nodes()['/']['compatible'] \
        .split(b'\0')[:2] == [b'oneplus,xigua', b'qcom,sm8550']
    vpath = OUT / 'scratch-vendor_boot_a.img'
    vpath.write_bytes(bytes(vendor))

    boot = bytearray(TEMPLATE_BOOT.read_bytes())
    cmd = (f'root=UUID={ROOT_UUID} rootwait rw console=tty0 loglevel=7 '
           f'panel_oneplus_aa536.refresh=120').encode()
    boot[44:44 + 512] = cmd + bytes(512 - len(cmd))
    bpath = OUT / 'scratch-boot_a.img'
    bpath.write_bytes(bytes(boot))

    # init_boot_a: reuse the empty-ramdisk image already built for boot-direct
    ipath = OUT / 'scratch-init_boot_a.img'
    ipath.write_bytes((OUT / 'boot-direct/init_boot_a.img').read_bytes())

    manifest = {
        'initramfs': {'compressed': len(rd), 'uncompressed': len(archive),
                      'fragment': rdsize, 'entries': len(names)},
        'busybox': {'path': str(BUSYBOX), 'bytes': len(busy), 'sha256': sha(busy)},
        'init_sha256': sha(init),
        'root_uuid': ROOT_UUID,
        'files': {
            'vendor': {'path': str(vpath), 'sha256': sha(vpath.read_bytes())},
            'boot': {'path': str(bpath), 'sha256': sha(bpath.read_bytes())},
            'init_boot': {'path': str(ipath), 'sha256': sha(ipath.read_bytes())},
        },
    }
    (OUT / 'scratch-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps(manifest, indent=2))
    print('PASS: scratch initramfs built')


if __name__ == '__main__':
    main()
