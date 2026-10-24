"""Build the minimal Ubuntu Touch initramfs and its vendor_boot.

Contents:
  /init                      boot script (mounts root, switch_root)
  /bin/busybox               static aarch64 busybox
  /lib/firmware/qcom/...     GPU firmware, so the adreno probe at ~0.8 s succeeds
                             before the root filesystem is mounted

The firmware is the reason this initramfs exists: the kernel on this device has
no userspace firmware fallback, and without an initramfs the GPU driver fails
with ENOENT before root is available (which is what broke Lomiri).

Run inside WSL (needs lz4 and the extracted firmware tree).
"""
import json
import os
import shutil
import struct
import subprocess
import sys
from pathlib import Path

ROOT = Path('/mnt/h/workspace/PJA110-Mainline')
sys.path.insert(0, str(ROOT / 'tools'))
from build_native_slot_image import align, avb_offset, sha      # noqa: E402
from build_init_marker_test import make_entry, parse_cpio        # noqa: E402
from fdt import FDT                                             # noqa: E402

OUT = ROOT / 'out/ut-test'
BUSYBOX = OUT / 'rescue-bin/busybox-static'
INIT = ROOT / 'image/install/probe-init.sh'
FW_TARBALL = OUT / 'fw/qcom-firmware.tar.gz'
FW_TREE = Path('/tmp/mini/root')
TEMPLATE_VENDOR = ROOT / 'out/ut-backup/backup-20261018-160329/vendor_boot_a.img'
TEMPLATE_BOOT = OUT / 'boot-direct/boot_a.img'

# Optional replacement DTB. When present it replaces the DTB area of the
# vendor_boot template (the template carries the stock 906-node blob).
DTB = OUT / 'oneplus-pja110.dtb'

# Only what the display/GPU path needs before root is mounted.
FIRMWARE = [
    'qcom/a740_sqe.fw',
    'qcom/gmu_gen70200.bin',
    'qcom/sm8550/xigua/a740_zap.mbn',
]


def lz4(args, data):
    with __import__('tempfile').TemporaryDirectory() as td:
        src = Path(td) / 'in.bin'
        dst = Path(td) / 'out.bin'
        src.write_bytes(data)
        subprocess.run(['lz4', *args, str(src), str(dst)],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        assert dst.is_file() and dst.stat().st_size > 0
        return dst.read_bytes()


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


def ensure_firmware():
    """Extract the firmware tarball when /tmp lost the previous tree."""
    needed = [FW_TREE / rel for rel in FIRMWARE]
    if all(p.is_file() for p in needed):
        return
    assert FW_TARBALL.is_file(), FW_TARBALL
    FW_TREE.mkdir(parents=True, exist_ok=True)
    subprocess.run(['tar', '-xzf', str(FW_TARBALL), '-C', str(FW_TREE)],
                   check=True)
    missing = [str(p) for p in needed if not p.is_file()]
    assert not missing, f'missing after extraction: {missing}'


def main():
    ensure_firmware()
    busy = BUSYBOX.read_bytes()
    init = INIT.read_bytes()

    files = [
        ('dev', b'', 0o040755),
        ('proc', b'', 0o040755),
        ('sys', b'', 0o040755),
        ('newroot', b'', 0o040755),
        ('tmp', b'', 0o041777),
        ('bin', b'', 0o040755),
        ('bin/busybox', busy, 0o100755),
        ('sbin', b'', 0o040755),
        ('usr', b'', 0o040755),
        ('usr/bin', b'', 0o040755),
        ('usr/sbin', b'', 0o040755),
        ('init', init, 0o100755),
        ('lib', b'', 0o040755),
        ('lib/firmware', b'', 0o040755),
        ('lib/firmware/qcom', b'', 0o040755),
        ('lib/firmware/qcom/sm8550', b'', 0o040755),
        ('lib/firmware/qcom/sm8550/xigua', b'', 0o040755),
    ]
    fw_sizes = {}
    for rel in FIRMWARE:
        src = FW_TREE / rel
        assert src.is_file(), src
        data = src.read_bytes()
        fw_sizes[rel] = len(data)
        files.append((f'lib/firmware/{rel}', data, 0o100644))

    archive = cpio(files)
    names = [n for _, n, _ in parse_cpio(archive)]
    assert 'init' in names and 'bin/busybox' in names
    assert 'lib/firmware/qcom/a740_sqe.fw' in names
    rd = lz4(['-z', '-l', '-12', '-f'], archive)
    print(f'initramfs: {len(archive)} B raw, {len(rd)} B lz4')

    # vendor_boot with this ramdisk
    vendor = bytearray(TEMPLATE_VENDOR.read_bytes())
    rdsize = struct.unpack_from('<I', vendor, 24)[0]
    hsize, dsize = struct.unpack_from('<II', vendor, 2096)
    rdoff = align(hsize)
    dtboff = align(rdoff + rdsize)
    tail = avb_offset(vendor)
    assert len(rd) <= rdsize, f'{len(rd)} > {rdsize}'
    orig = bytes(vendor)
    vendor[rdoff:rdoff + rdsize] = rd + bytes(rdsize - len(rd))

    # Replace the DTB area when a rebuilt blob is available.
    dtb_note = None
    if DTB.is_file():
        blob = DTB.read_bytes()
        assert blob[:4] == b'\xd0\x0d\xfe\xed', 'not an FDT blob'
        assert len(blob) <= dsize, f'DTB {len(blob)} > area {dsize}'
        vendor[dtboff:dtboff + dsize] = blob + bytes(dsize - len(blob))
        dtb_note = {'path': str(DTB), 'bytes': len(blob), 'sha256': sha(blob)}
        print(f'DTB replaced: {len(blob)} B into a {dsize} B area')
    else:
        assert vendor[dtboff:tail] == orig[dtboff:tail], 'DTB changed unexpectedly'

    assert FDT(bytes(vendor[dtboff:dtboff + dsize])).nodes()['/']['compatible'] \
        .split(b'\0')[:2] == [b'oneplus,pja110', b'qcom,sm8550']
    vpath = OUT / 'probe-vendor_boot_a.img'
    vpath.write_bytes(bytes(vendor))

    # boot: kernel with a plain root=, the initramfs does the mounting
    boot = bytearray(TEMPLATE_BOOT.read_bytes())
    cmd = (b'root=/dev/sda14 rootwait rw console=tty0 loglevel=7 '
           b'panel_oneplus_aa536.refresh=120')
    boot[44:44 + 512] = cmd + bytes(512 - len(cmd))
    bpath = OUT / 'probe-boot_a.img'
    bpath.write_bytes(bytes(boot))

    manifest = {
        'ramdisk': {'raw': len(archive), 'lz4': len(rd), 'fragment': rdsize},
        'firmware': fw_sizes,
        'dtb': dtb_note,
        'files': {
            'vendor': {'path': str(vpath), 'sha256': sha(vpath.read_bytes())},
            'boot': {'path': str(bpath), 'sha256': sha(bpath.read_bytes())},
        },
        'init_sha256': sha(init),
        'busybox_sha256': sha(busy),
    }
    (OUT / 'probe-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps(manifest, indent=2))
    print('PASS: probe initramfs built')


if __name__ == '__main__':
    main()
