#!/usr/bin/env python3
"""End-to-end test of the boot.img packer using a synthetic kernel.

We do not have a built mainline arm64 Image yet, so build a fake but
structurally valid one (correct EFI-stub header: "MZ", ARMd magic at +56)
and check that pack -> parse round-trips, and that the DTB is appended where
we expect.
"""
import os
import struct
import subprocess
import sys

WS = r'H:\WorkSpace\PJA110-Mainline'
TMP = os.path.join(WS, 'build')
os.makedirs(TMP, exist_ok=True)


def make_fake_image(path, size=4 * 1024 * 1024):
    """Minimal arm64 Image: EFI stub magic + size fields."""
    buf = bytearray(size)
    struct.pack_into('<I', buf, 0, 0xfa405a4d)      # "MZ" branch (code0)
    struct.pack_into('<I', buf, 4, 0x14b3bfff)      # code1
    struct.pack_into('<Q', buf, 8, 0)               # text_offset
    struct.pack_into('<Q', buf, 16, size)           # image_size
    struct.pack_into('<Q', buf, 24, 0xa)            # flags
    struct.pack_into('<4s', buf, 56, b'ARM\x64')    # magic
    struct.pack_into('<I', buf, 60, 0)              # res1
    open(path, 'wb').write(bytes(buf))
    return path


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    print(r.stdout)
    if r.stderr.strip():
        print('STDERR: %s' % r.stderr[:2000])
    return r.returncode


img = make_fake_image(os.path.join(TMP, 'fake-Image'))
print('made %s (%d bytes)' % (img, os.path.getsize(img)))

dtb = os.path.join(WS, 'dts', 'sm8550-oneplus-xigua-16G.dtb')
out = os.path.join(TMP, 'boot-xigua-test.img')

py = sys.executable
print('=== pack ===')
rc = run([py, os.path.join(WS, 'tools', 'bootimg.py'), 'pack',
          '--kernel', img, '--dtb', dtb,
          '--stock', os.path.join(WS, 'boot-A14.img'),
          '--cmdline', 'console=ttyMSM0,115200 loglevel=8',
          '-o', out])
if rc != 0:
    sys.exit(rc)

print('=== parse back ===')
run([py, os.path.join(WS, 'tools', 'bootimg.py'), 'parse', out])

print('=== verify DTB is appended inside the kernel field ===')
data = open(out, 'rb').read()
ksize = struct.unpack_from('<I', data, 8)[0]
kernel_field = data[4096:4096 + ksize]
img_size, dtb_size = os.path.getsize(img), os.path.getsize(dtb)
print('  kernel_size field     = %d' % ksize)
print('  expected Image+DTB    = %d (%d + %d)' % (img_size + dtb_size, img_size, dtb_size))
print('  match: %s' % (ksize == img_size + dtb_size))
print('  DTB magic at Image end: %s'
      % (kernel_field[img_size:img_size + 4] == b'\xd0\x0d\xfe\xed'))
print('  DTB byte-identical     : %s'
      % (kernel_field[img_size:] == open(dtb, 'rb').read()))
print()
print('RESULT: %s' % ('PASS' if (ksize == img_size + dtb_size
                                 and kernel_field[img_size:] == open(dtb, 'rb').read())
                       else 'FAIL'))
