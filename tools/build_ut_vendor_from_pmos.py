"""Build the UT vendor_boot by reusing the pmOS initramfs tree.

The pmOS initramfs is known to execute on this device; a hand-built minimal
archive failed at exec time because its busybox could not resolve the musl
loader. Instead of rebuilding that environment, this keeps every pmOS entry and
replaces only /init with the UT boot script.

Output: out/ut-test/ut-vendor_boot_a.img
"""
import json
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from build_native_slot_image import (DEFAULT_VENDOR, align, avb_offset, lz4,
                                     parse_cpio, sha)
from build_init_marker_test import make_entry
from fdt import FDT

OUT = ROOT / 'out/ut-test'
BASE = ROOT / 'out/ut-backup/backup-20261018-160329/vendor_boot_a.img'
UT_INIT = ROOT / 'ut-init.sh'


def parse_boundary(blob):
    """Return (ramdisk_offset, ramdisk_size) of the vendor fragment."""
    rdsize = struct.unpack_from('<I', blob, 24)[0]
    hsize, _ = struct.unpack_from('<II', blob, 2096)
    return align(hsize), rdsize


def serialise(entries):
    out = bytearray()
    for fields, name, data in entries:
        out += make_entry(fields, name, data)
    # make_entry already pads each entry to 4 bytes; the kernel also accepts a
    # final zero block, which keeps parity with the pmOS archive.
    while len(out) % 512:
        out.append(0)
    return bytes(out)


def main():
    assert BASE.is_file(), BASE
    assert UT_INIT.is_file(), UT_INIT

    vendor = BASE.read_bytes()
    rdoff, rdsize = parse_boundary(vendor)
    rd = vendor[rdoff:rdoff + rdsize]
    archive = lz4(['-d', '-l', '-c'], rd)
    entries = parse_cpio(archive)

    init_entry = None
    for idx, (fields, name, data) in enumerate(entries):
        if name.lstrip('./') == 'init':
            init_entry = idx
            break
    assert init_entry is not None, [n for _, n, _ in entries][:10]

    fields, name, _ = entries[init_entry]
    new_fields = list(fields)
    new_fields[6] = len(UT_INIT.read_bytes())
    entries[init_entry] = (new_fields, name, UT_INIT.read_bytes())

    rebuilt = serialise(entries)
    rd_new = lz4(['-z', '-l', '-12', '-c'], rebuilt)
    assert len(rd_new) <= rdsize, f'ramdisk {len(rd_new)} > fragment {rdsize}'

    out = bytearray(vendor)
    out[rdoff:rdoff + rdsize] = rd_new + bytes(rdsize - len(rd_new))
    assert out[rdoff + rdsize:] == vendor[rdoff + rdsize:]

    # DTB must still be intact
    hsize, dsize = struct.unpack_from('<II', out, 2096)
    dtboff = align(rdoff + rdsize)
    assert FDT(out[dtboff:dtboff + dsize]).nodes()['/']['compatible'] \
        .split(b'\0')[:2] == [b'oneplus,xigua', b'qcom,sm8550']

    target = OUT / 'ut-vendor_boot_a.img'
    target.write_bytes(bytes(out))

    manifest = {
        'base': str(BASE),
        'entry_count': len(entries),
        'ramdisk': {'compressed': len(rd_new), 'uncompressed': len(rebuilt),
                    'fragment': rdsize, 'slack': rdsize - len(rd_new)},
        'output': {'path': str(target), 'bytes': target.stat().st_size,
                   'sha256': sha(target.read_bytes())},
        'init_sha256': sha(UT_INIT.read_bytes()),
    }
    (OUT / 'ut-vendor-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps(manifest, indent=2))
    print('PASS: UT vendor_boot built from the pmOS initramfs')


if __name__ == '__main__':
    main()
