#!/usr/bin/env python3
"""Extract a single partition from an AOSP update_engine payload.bin.

No external dependencies (uses the stdlib lzma/bz2/zlib), so it works on a
plain Windows Python install. Handles the operation types that matter for
full/flash OTA packages: REPLACE, REPLACE_BZ, REPLACE_XZ, ZERO, and reports
operations it cannot apply (BSDIFF/SOURCE_*, which need the source image).

Usage:
    python extract_partition.py payload.bin dtbo [-o dtbo.img]
    python extract_partition.py payload.bin --list
"""
import argparse
import bz2
import lzma
import os
import struct
import sys
import zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from parse_payload_manifest import fields, WT_LEN, WT_VARINT  # noqa: E402

BLOCK = 4096

# InstallOperation.Type, AOSP update_metadata.proto
OP_REPLACE = 0
OP_REPLACE_BZ = 1
OP_MOVE = 2
OP_BSDIFF = 3
OP_SOURCE_COPY = 4
OP_SOURCE_BSDIFF = 5
OP_ZERO = 6
OP_DISCARD = 7
OP_REPLACE_XZ = 8
OP_PUFFDIFF = 9
OP_BROTLI_BSDIFF = 10
OP_ZUCCHINI = 11
OP_LZ4DIFF_BSDIFF = 12
OP_LZ4DIFF_PUFFDIFF = 13

OP_NAMES = {
    0: "REPLACE", 1: "REPLACE_BZ", 2: "MOVE", 3: "BSDIFF",
    4: "SOURCE_COPY", 5: "SOURCE_BSDIFF", 6: "ZERO", 7: "DISCARD",
    8: "REPLACE_XZ", 9: "PUFFDIFF", 10: "BROTLI_BSDIFF",
    11: "ZUCCHINI", 12: "LZ4DIFF_BSDIFF", 13: "LZ4DIFF_PUFFDIFF",
}


def read_header(fh):
    """Returns (data_offset, manifest_bytes)."""
    fh.seek(0)
    magic = fh.read(4)
    if magic != b"CrAU":
        sys.exit(f"not an update_engine payload (magic={magic!r})")
    version = int.from_bytes(fh.read(8), "big")
    manifest_size = int.from_bytes(fh.read(8), "big")
    sig_size = int.from_bytes(fh.read(4), "big") if version >= 2 else 0
    manifest = fh.read(manifest_size)
    return 24 + manifest_size + sig_size, manifest


def partition_update(manifest, wanted):
    """Find the PartitionUpdate message for `wanted`."""
    for fnum, wtype, val in fields(manifest):
        if fnum == 13 and wtype == WT_LEN:
            name = None
            for pnum, ptype, pval in fields(val):
                if pnum == 1 and ptype == WT_LEN:
                    name = pval.decode("utf-8", "replace")
                    break
            if name == wanted:
                return val
    return None


def extents(msg):
    out = []
    for fnum, wtype, val in fields(msg):
        if fnum == 1:
            start = val
        elif fnum == 2:
            out.append((start, val))
    return out


def operations(pu):
    """Yield (type, data_offset, data_length, [dst extents]).

    Operations live in the repeated message field that carries a type, a
    data offset/length and dst_extents; vendor forks move the field number
    around, so detect it by shape instead of hard-coding it.
    """
    for fnum, wtype, val in fields(pu):
        if wtype != WT_LEN or fnum == 1:
            continue
        op_type = data_offset = data_length = None
        dsts = []
        looks_like_op = True
        for onum, otype, oval in fields(val):
            if onum == 1 and otype == WT_VARINT and oval <= 20:
                op_type = oval
            elif onum == 2 and otype == WT_VARINT:
                data_offset = oval
            elif onum == 3 and otype == WT_VARINT:
                data_length = oval
            elif onum == 6 and otype == WT_LEN:
                dsts = extents(oval)
            elif onum in (4, 5, 7):
                pass                      # src_extents / src_length / dst_length
            elif onum in (8, 9) and otype == WT_LEN and len(oval) == 32:
                pass                      # hashes
            else:
                looks_like_op = False
                break
        if looks_like_op and op_type is not None:
            yield op_type, data_offset or 0, data_length or 0, dsts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("payload")
    ap.add_argument("partition", nargs="?")
    ap.add_argument("-o", "--output")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()

    with open(args.payload, "rb") as fh:
        data_off, manifest = read_header(fh)

        names = []
        for fnum, wtype, val in fields(manifest):
            if fnum == 13 and wtype == WT_LEN:
                for pnum, ptype, pval in fields(val):
                    if pnum == 1 and ptype == WT_LEN:
                        names.append(pval.decode("utf-8", "replace"))
                        break

        if args.list or not args.partition:
            print("\n".join(names))
            return

        pu = partition_update(manifest, args.partition)
        if pu is None:
            sys.exit(f"partition {args.partition!r} not in payload "
                     f"(known: {', '.join(sorted(names))})")

        out_path = args.output or f"{args.partition}.img"
        unsupported = []
        written = 0
        with open(out_path, "wb") as out:
            for op_type, off, length, dsts in operations(pu):
                if op_type in (OP_ZERO, OP_DISCARD):
                    payload = b""
                else:
                    fh.seek(data_off + off)
                    raw = fh.read(length)
                    if op_type == OP_REPLACE:
                        payload = raw
                    elif op_type == OP_REPLACE_BZ:
                        payload = bz2.decompress(raw)
                    elif op_type == OP_REPLACE_XZ:
                        payload = lzma.decompress(raw)
                    elif op_type == OP_MOVE:
                        continue
                    else:
                        unsupported.append(OP_NAMES.get(op_type, op_type))
                        continue
                pos = 0
                for start, nblocks in dsts:
                    size = nblocks * BLOCK
                    chunk = payload[pos:pos + size] if payload else b"\0" * size
                    out.seek(start * BLOCK)
                    out.write(chunk)
                    pos += size
                    written = max(written, start * BLOCK + len(chunk))
                if op_type == OP_REPLACE_XZ and not dsts:
                    out.seek(0)
                    out.write(payload)
                    written = max(written, len(payload))

        if unsupported:
            uniq = sorted(set(map(str, unsupported)))
            print(f"WARNING: skipped unsupported ops {uniq} "
                  f"(need the source image / extra codecs)", file=sys.stderr)
        print(f"{args.partition}: wrote {out_path} "
              f"({os.path.getsize(out_path):,} bytes, high-water {written:,})")


if __name__ == "__main__":
    main()
