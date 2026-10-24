#!/usr/bin/env python3
"""Android boot image (header v3/v4) parse + pack, no external tools.

Reverse-engineered from this device's own stock image, so the packer reproduces
exactly what the ABL expects.

Layout established from vendor boot-A14.img:
    offset 0x0000  header v4, header_size = 1584 (rest of page zero-padded)
    offset 0x1000  kernel   (raw arm64 EFI-stub Image -- starts with "MZ")
    ...            ramdisk  (absent on this device: ramdisk_size = 0)
    ...            (v4) boot_signature, size 0 here
    page-aligned   AVB0 vbmeta structure (only in the stock, signed image)
    rest of the 192 MiB partition: zero padding

The DTB is NOT a separate section in header v4. The Ace 3 port (and this tool's
--dtb option) therefore APPEND the DTB to the kernel Image and gzip the result
into the kernel field -- that is the trick that makes `fastboot boot` work
without touching the dtbo partition.

Usage:
    # inspect
    python bootimg.py parse boot-A14.img

    # build: Image + DTB, gzipped, header v4
    python bootimg.py pack --kernel Image --dtb sm8550-oneplus-xigua.dtb \
        --dtb-variant sm8550-oneplus-xigua-16G.dtb -o boot-xigua.img

    # round-trip self test against the stock image
    python bootimg.py selftest boot-A14.img
"""
import argparse
import gzip
import os
import struct
import sys

WS = r'H:\WorkSpace\PJA110-Mainline'
BOOT_MAGIC = b'ANDROID!'
PAGE = 4096
HEADER_SIZE_V4 = 1584


# --------------------------------------------------------------------------
# header v3/v4
# --------------------------------------------------------------------------
def decode_os_version(v):
    """mkbootimg packs os_version and os_patch_level into one u32.

    AOSP: (major << 25) | (minor << 18) | ((year-2000) << 11) | (month << 4)
    Note: the stock image on this device does NOT follow AOSP's year packing,
    so we always copy its raw value instead of recomputing (see --os-version).
    """
    return {
        'raw': '0x%08x' % v,
        'major': (v >> 25) & 0x7F,
        'minor': (v >> 18) & 0x7F,
        'year': 2000 + ((v >> 11) & 0x7F),
        'month': (v >> 4) & 0x0F,
        'low16': '0x%04x' % (v & 0xFFFF),
    }


def parse_os_version(s):
    """Accept 0x..., 'major.minor', or 'major.minor.patch'/'major.minor.yyyy-mm'."""
    s = s.strip()
    if s.lower().startswith('0x'):
        return int(s, 16)
    parts = s.split('.')
    if len(parts) >= 2:
        major, minor = int(parts[0]), int(parts[1])
        year = month = 0
        if len(parts) >= 3 and parts[2]:
            p = parts[2].replace('-', '.')
            sub = p.split('.')
            if len(sub) == 2:
                y, m = int(sub[0]), int(sub[1])
                year = y - 2000 if y >= 2000 else y
                month = m
        return (major << 25) | (minor << 18) | (year << 11) | (month << 4)
    return int(s, 0)


def page_align(n, page=PAGE):
    return (n + page - 1) // page * page


class BootImage:
    def __init__(self):
        self.kernel = b''
        self.ramdisk = b''
        self.dtb = b''
        self.signature = b''
        self.cmdline = b''
        self.os_version = 0x1a000184        # copied from the stock image
        self.header_version = 4
        self.page = PAGE
        self.extra = b''                    # trailing vbmeta, preserved if asked

    # -- parse ------------------------------------------------------------
    @classmethod
    def parse(cls, path, keep_extra=False):
        b = open(path, 'rb').read()
        if b[:8] != BOOT_MAGIC:
            raise ValueError('not a boot image: magic=%r' % b[:8])
        self = cls()
        (kernel_size, ramdisk_size, os_version, header_size) = struct.unpack_from('<4I', b, 8)
        (header_version,) = struct.unpack_from('<I', b, 40)
        self.os_version = os_version
        self.header_version = header_version
        self.cmdline = b[44:44 + 1536].rstrip(b'\0')
        sig_size = 0
        if header_version >= 4 and len(b) >= 1584:
            (sig_size,) = struct.unpack_from('<I', b, 1580)

        off = PAGE
        self.kernel = b[off:off + kernel_size]
        off += page_align(kernel_size)
        self.ramdisk = b[off:off + ramdisk_size]
        off += page_align(ramdisk_size)
        if sig_size:
            self.signature = b[off:off + sig_size]
            off += page_align(sig_size)

        # anything page-aligned after the known sections is vendor extra
        # (on this device: an AVB0 vbmeta structure + zero padding)
        if keep_extra:
            rest = b[page_align(off):]
            nz = rest.rstrip(b'\0')
            self.extra = nz
        self.total_size = len(b)
        return self

    # -- pack -------------------------------------------------------------
    def pack(self, dtb=None, cmdline=None, page=None):
        """Return the raw partition image bytes."""
        page = page or self.page
        kernel = self.kernel
        if dtb is not None:
            self.dtb = dtb
        if self.dtb:
            kernel = kernel + self.dtb
        if cmdline is not None:
            self.cmdline = cmdline if isinstance(cmdline, bytes) else cmdline.encode()

        hv = self.header_version
        hdr = bytearray(HEADER_SIZE_V4 if hv >= 4 else 1580)
        struct.pack_into('<8s', hdr, 0, BOOT_MAGIC)
        struct.pack_into('<I', hdr, 8, len(kernel))
        struct.pack_into('<I', hdr, 12, len(self.ramdisk))
        struct.pack_into('<I', hdr, 16, self.os_version)
        struct.pack_into('<I', hdr, 20, HEADER_SIZE_V4 if hv >= 4 else 1580)
        struct.pack_into('<4I', hdr, 24, 0, 0, 0, 0)
        struct.pack_into('<I', hdr, 40, hv)
        cl = self.cmdline[:1536]
        hdr[44:44 + len(cl)] = cl
        if hv >= 4:
            struct.pack_into('<I', hdr, 1580, len(self.signature))

        out = bytearray()
        out += bytes(hdr) + b'\0' * (page - len(hdr))
        out += kernel + b'\0' * (page_align(len(kernel)) - len(kernel))
        if self.ramdisk:
            out += self.ramdisk + b'\0' * (page_align(len(self.ramdisk)) - len(self.ramdisk))
        if self.signature:
            out += self.signature + b'\0' * (page_align(len(self.signature)) - len(self.signature))
        return bytes(out)

    # -- report -----------------------------------------------------------
    def describe(self, label=''):
        print('%sheader_version = %d' % (label, self.header_version))
        print('%sos_version     = %s' % (label, decode_os_version(self.os_version)))
        print('%skernel         = %d bytes (%.2f MiB)' % (label, len(self.kernel), len(self.kernel) / 2**20))
        print('%sramdisk        = %d bytes' % (label, len(self.ramdisk)))
        print('%scmdline        = %r' % (label, self.cmdline))
        print('%sextra(vbmeta)  = %d bytes' % (label, len(self.extra)))


# --------------------------------------------------------------------------
def cmd_parse(args):
    img = BootImage.parse(args.image, keep_extra=True)
    print('=== %s (%d bytes, %.2f MiB) ==='
          % (os.path.basename(args.image), img.total_size, img.total_size / 2**20))
    img.describe('  ')
    first = img.kernel[:64]
    print('  kernel first bytes = %r' % first[:8])
    if first[:2] == b'\x1f\x8b':
        print('  kernel is GZIP')
        d = gzip.decompress(img.kernel)
        print('  decompressed       = %d bytes (%.2f MiB)' % (len(d), len(d) / 2**20))
        i = d.find(b'\xd0\x0d\xfe\xed')
        print('  FDT inside         = %s' % ('0x%x' % i if i >= 0 else 'no'))
    elif first[56:60] == b'ARM\x64':
        (isz,) = struct.unpack_from('<Q', img.kernel, 16)
        print('  raw arm64 EFI-stub Image, image_size field = %d (%.2f MiB)'
              % (isz, isz / 2**20))
        print('  FDT appended after Image? %s'
              % (img.kernel[isz:isz + 4] == b'\xd0\x0d\xfe\xed'))
    if img.extra:
        print('  trailing data starts with %r' % img.extra[:16])


def cmd_pack(args):
    base = BootImage()
    if args.stock:
        s = BootImage.parse(args.stock, keep_extra=False)
        base.os_version = s.os_version          # safest: reuse known-good value
        base.header_version = s.header_version
        print('inherited os_version 0x%08x and header v%d from %s'
              % (base.os_version, base.header_version, os.path.basename(args.stock)))

    if args.os_version:
        base.os_version = parse_os_version(args.os_version)
        print('os_version overridden -> 0x%08x (%s)'
              % (base.os_version, decode_os_version(base.os_version)))

    if not os.path.exists(args.kernel):
        sys.exit('kernel not found: %s' % args.kernel)
    kernel = open(args.kernel, 'rb').read()
    print('kernel: %s (%d bytes, %.2f MiB)'
          % (os.path.basename(args.kernel), len(kernel), len(kernel) / 2**20))

    dtb = b''
    if args.dtb:
        if not os.path.exists(args.dtb):
            sys.exit('dtb not found: %s' % args.dtb)
        dtb = open(args.dtb, 'rb').read()
        print('dtb   : %s (%d bytes)' % (os.path.basename(args.dtb), len(dtb)))
        if dtb[:4] != b'\xd0\x0d\xfe\xed':
            sys.exit('%s is not a DTB (bad magic)' % args.dtb)

    base.kernel = kernel
    if args.ramdisk:
        base.ramdisk = open(args.ramdisk, 'rb').read()
        print('ramdisk: %d bytes' % len(base.ramdisk))

    cmdline = args.cmdline or ''
    raw = base.pack(dtb=dtb or None, cmdline=cmdline)

    if args.pad_to:
        target = args.pad_to
        if len(raw) > target:
            sys.exit('image %d exceeds pad target %d' % (len(raw), target))
        raw = raw + b'\0' * (target - len(raw))

    open(args.output, 'wb').write(raw)
    print('wrote %s (%d bytes, %.2f MiB)'
          % (args.output, len(raw), len(raw) / 2**20))

    # immediate read-back verification
    back = BootImage.parse(args.output)
    print()
    print('--- read-back check ---')
    back.describe('  ')
    ok = (len(back.kernel) == len(kernel) + len(dtb)
          and back.kernel[:len(kernel)] == kernel
          and (not dtb or back.kernel[-len(dtb):] == dtb)
          and back.os_version == base.os_version
          and back.cmdline == (cmdline.encode() if cmdline else b''))
    print('  self-check: %s' % ('PASS' if ok else 'FAIL'))


def cmd_selftest(args):
    """Repack the stock kernel and confirm the result is byte-identical."""
    src = open(args.image, 'rb').read()
    img = BootImage.parse(args.image, keep_extra=False)
    print('stock: %d bytes' % len(src))
    out = img.pack()
    print('repacked: %d bytes' % len(out))
    same = out == src[:len(out)]
    print('header+kernel region identical: %s' % same)
    if not same:
        for i in range(min(len(out), len(src))):
            if out[i] != src[i]:
                print('  first difference at 0x%x: ours=%02x stock=%02x'
                      % (i, out[i], src[i]))
                break
    print('stock tail beyond our output: %d bytes (AVB footer + padding)'
          % (len(src) - len(out)))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)

    p = sub.add_parser('parse', help='dump a boot image layout')
    p.add_argument('image')
    p.set_defaults(func=cmd_parse)

    p = sub.add_parser('pack', help='build a boot image')
    p.add_argument('--kernel', required=True, help='arm64 Image (raw or gzipped)')
    p.add_argument('--dtb', help='DTB to append to the kernel')
    p.add_argument('--ramdisk', help='optional ramdisk')
    p.add_argument('-o', '--output', required=True)
    p.add_argument('--cmdline', default='', help='kernel cmdline')
    p.add_argument('--os-version', help='override os_version (0x... or M.m[.yyyy-mm])')
    p.add_argument('--stock', help='inherit os_version/header_version from this image')
    p.add_argument('--pad-to', type=int, help='zero-pad output to this size (partition size)')
    p.add_argument('--gzip-kernel', action='store_true', help='gzip the kernel (not needed: ABL accepts raw Image)')
    p.set_defaults(func=cmd_pack)

    p = sub.add_parser('selftest', help='repack stock image and compare')
    p.add_argument('image')
    p.set_defaults(func=cmd_selftest)

    args = ap.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
