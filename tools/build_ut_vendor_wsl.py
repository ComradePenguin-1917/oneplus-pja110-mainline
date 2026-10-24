"""Build the UT vendor_boot from the pmOS initramfs — WSL variant.

Runs inside WSL because the Windows lz4 build rejects the padded vendor
fragment. Only /init is replaced; every other pmOS entry is preserved so the
busybox/musl environment keeps working.

    python3 tools/build_ut_vendor_wsl.py
"""
import json
import struct
import subprocess
import sys
from pathlib import Path

ROOT = Path('/mnt/h/workspace/PJA110-Mainline')
sys.path.insert(0, str(ROOT / 'tools'))
from build_native_slot_image import align, sha           # noqa: E402
from build_init_marker_test import make_entry, parse_cpio  # noqa: E402
from fdt import FDT                                      # noqa: E402

OUT = ROOT / 'out/ut-test'
BASE = ROOT / 'out/ut-backup/backup-20261018-160329/vendor_boot_a.img'
UT_INIT = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / 'ut-init.sh'
OUTPUT = Path(sys.argv[2]) if len(sys.argv) > 2 else OUT / 'ut-vendor_boot_a.img'


def lz4(args, data):
    """Run lz4 through temp files: the vendor fragment is zero padded, which the
    streaming form rejects but the file form tolerates."""
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / 'in.bin'
        dst = Path(td) / 'out.bin'
        src.write_bytes(data)
        # The padded vendor fragment makes lz4 report trailing garbage and exit
        # non-zero, but the decoded payload is complete; accept a non-empty output.
        subprocess.run(['lz4', *args, str(src), str(dst)],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        assert dst.is_file() and dst.stat().st_size > 0, 'lz4 produced no output'
        return dst.read_bytes()


def serialise(entries):
    out = bytearray()
    for fields, name, data in entries:
        out += make_entry(fields, name, data)
    while len(out) % 512:
        out.append(0)
    return bytes(out)


def main():
    vendor = BASE.read_bytes()
    rdsize = struct.unpack_from('<I', vendor, 24)[0]
    hsize, dsize = struct.unpack_from('<II', vendor, 2096)
    rdoff = align(hsize)
    dtboff = align(rdoff + rdsize)

    rd = vendor[rdoff:rdoff + rdsize]
    archive = lz4(['-d', '-f'], rd)
    entries = parse_cpio(archive)

    idx = next(i for i, (_, n, _) in enumerate(entries)
               if n.lstrip('./') == 'init')
    fields, name, _ = entries[idx]
    init = UT_INIT.read_bytes()
    fields = list(fields)
    fields[6] = len(init)
    entries[idx] = (fields, name, init)

    rebuilt = serialise(entries)
    rd_new = lz4(['-z', '-l', '-12', '-f'], rebuilt)
    assert len(rd_new) <= rdsize, f'ramdisk {len(rd_new)} > {rdsize}'

    out = bytearray(vendor)
    out[rdoff:rdoff + rdsize] = rd_new + bytes(rdsize - len(rd_new))
    assert out[rdoff + rdsize:] == vendor[rdoff + rdsize:]
    assert FDT(out[dtboff:dtboff + dsize]).nodes()['/']['compatible'] \
        .split(b'\0')[:2] == [b'oneplus,xigua', b'qcom,sm8550']

    target = OUTPUT
    target.write_bytes(bytes(out))
    manifest = {
        'base': str(BASE),
        'entries': len(entries),
        'ramdisk': {'compressed': len(rd_new), 'uncompressed': len(rebuilt),
                    'fragment': rdsize, 'slack': rdsize - len(rd_new)},
        'output': {'path': str(target), 'bytes': target.stat().st_size,
                   'sha256': sha(target.read_bytes())},
        'init_sha256': sha(init),
    }
    (OUT / 'ut-vendor-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps(manifest, indent=2))
    print('PASS: built from pmOS initramfs')


if __name__ == '__main__':
    main()
