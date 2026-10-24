#!/usr/bin/env python3
"""Change a build.prop witness in init_boot while preserving factory init."""
import hashlib
import os
import struct
import subprocess

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_BOOT = os.path.join(WS, "backup", "init_boot_b.img")
OUT_CPIO = os.path.join(WS, "out", "initramfs-stock-marker.cpio")
OUT_BOOT = os.path.join(WS, "out", "init_boot_b-stock-marker.img")
LZ4 = r"D:\msys64\ucrt64\bin\lz4.exe"
PAGE = 4096


def align(value):
    return (value + 3) & ~3


def lz4(args, data):
    return subprocess.run([LZ4, *args], input=data, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, check=True).stdout


def parse_cpio(blob):
    entries = []
    pos = 0
    while pos + 110 <= len(blob):
        if blob[pos:pos + 6] not in (b"070701", b"070702"):
            raise ValueError("invalid newc archive at 0x%x" % pos)
        fields = [int(blob[pos + off:pos + off + 8], 16)
                  for off in range(6, 110, 8)]
        filesize, namesize = fields[6], fields[11]
        name_start = pos + 110
        name = blob[name_start:name_start + namesize - 1].decode()
        data_start = align(name_start + namesize)
        data = blob[data_start:data_start + filesize]
        entries.append((fields, name, data))
        pos = align(data_start + filesize)
        if name == "TRAILER!!!":
            break
    return entries


def make_entry(fields, name, data):
    f = list(fields)
    f[11] = len(name.encode()) + 1
    f[6] = len(data)
    f[12] = 0
    header = b"070701" + b"".join(("%08x" % x).encode() for x in f)
    out = bytearray(header)
    out += name.encode() + b"\0"
    out += b"\0" * ((-len(out)) & 3)
    out += data
    out += b"\0" * ((-len(out)) & 3)
    return bytes(out)


def main():
    original = bytearray(open(SRC_BOOT, "rb").read())
    old_size = struct.unpack_from("<I", original, 12)[0]
    old_end = PAGE + ((old_size + PAGE - 1) // PAGE * PAGE)
    compressed_old = bytes(original[PAGE:PAGE + old_size])
    cpio = lz4(["-d", "-l", "-c"], compressed_old)
    entries = parse_cpio(cpio)
    old_prop = b"ro.bootimage.build.tags=release-keys\n"
    # Reuse an existing property name so Android's property contexts accept it.
    new_prop = b"ro.bootimage.build.tags=x\n"
    if len(new_prop) > len(old_prop):
        raise SystemExit("marker property does not fit replacement line")
    if not any(n == "system/etc/ramdisk/build.prop" for f, n, d in entries):
        raise SystemExit("stock ramdisk has no build.prop")
    out = bytearray()
    for fields, name, data in entries:
        if name == "system/etc/ramdisk/build.prop":
            if old_prop not in data:
                raise SystemExit("target build.prop line not found")
            data = data.replace(old_prop, new_prop, 1)
            data = data.replace(b"# end of file\n", b"#\n", 1)
            out += make_entry(fields, name, data)
        else:
            out += make_entry(fields, name, data)
    open(OUT_CPIO, "wb").write(out)
    reparsed = parse_cpio(bytes(out))
    assert len(reparsed) == len(entries)
    assert reparsed[-1][1] == 'TRAILER!!!'
    for (_, old_name, old_data), (_, name, data) in zip(entries, reparsed):
        assert name == old_name
        if name != 'system/etc/ramdisk/build.prop':
            assert data == old_data, name
        else:
            assert new_prop in data and old_prop not in data
    # The factory ramdisk uses high-compression legacy LZ4 and fills the
    # allocated slot exactly; use the same level so the replacement fits.
    compressed = lz4(["-z", "-l", "-12", "-c"], bytes(out))
    print("compressed candidate: %d bytes (slot %d)" % (len(compressed), old_size))
    if len(compressed) >= old_size:
        raise SystemExit("new ramdisk does not fit in original slot")
    struct.pack_into("<I", original, 12, len(compressed))
    original[PAGE:PAGE + len(compressed)] = compressed
    original[PAGE + len(compressed):old_end] = b"\0" * (old_end - PAGE - len(compressed))
    open(OUT_BOOT, "wb").write(original)
    print("stock cpio: %d bytes" % len(cpio))
    print("new cpio:   %d bytes -> %s" % (len(out), OUT_CPIO))
    print("ramdisk:    %d bytes (slot %d)" % (len(compressed), old_size))
    print("image:      %d bytes -> %s" % (len(original), OUT_BOOT))
    print("sha256:     %s" % hashlib.sha256(original).hexdigest())


if __name__ == "__main__":
    main()
