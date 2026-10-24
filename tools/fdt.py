#!/usr/bin/env python3
"""Flattened Device Tree (FDT/DTB) reader, plus Android dt_table (DTBO) support.

Pure stdlib. Two file kinds are understood:

  * a plain DTB  (starts with magic 0xd00dfeed)
  * a DTBO image (starts with magic 0xd7b7ab1e) containing several DTBs

Examples
--------
  python fdt.py dtbo-A14.img --list                  # list the DTBs inside a DTBO
  python fdt.py dtbo-A14.img --entry 0 --projects    # which device each entry targets
  python fdt.py dtbo-A14.img --entry 0 --find reserved-memory
  python fdt.py dtbo-A14.img --entry 0 --resmem      # decoded reserved-memory map
  python fdt.py boot-A14.img --scan                  # find embedded FDT magic offsets
"""
import argparse
import struct
import sys

FDT_MAGIC = 0xD00DFEED
DTBO_MAGIC = 0xD7B7AB1E

FDT_BEGIN_NODE, FDT_END_NODE, FDT_PROP, FDT_NOP, FDT_END = 1, 2, 3, 4, 9


def _u32(buf, off):
    return struct.unpack_from('>I', buf, off)[0]


class FDT:
    """Minimal device tree parser: walks the structure block into a node list."""

    def __init__(self, blob):
        self.blob = blob
        if _u32(blob, 0) != FDT_MAGIC:
            raise ValueError('not an FDT blob (bad magic)')
        self.totalsize = _u32(blob, 4)
        self.off_struct = _u32(blob, 8)
        self.off_strings = _u32(blob, 12)
        self.off_rsvmap = _u32(blob, 16)
        self.version = _u32(blob, 20)
        self.size_strings = _u32(blob, 32)

    # -- helpers ---------------------------------------------------------
    @staticmethod
    def _join(parts):
        """Build an absolute node path, tolerating the empty root name."""
        segs = [p for p in parts if p]
        return '/' + '/'.join(segs) if segs else '/'

    def _string(self, off):
        end = self.blob.index(b'\0', self.off_strings + off)
        return self.blob[self.off_strings + off:end].decode('utf-8', 'replace')

    def reserved_memory(self):
        """Flat memory reservations from the reserve map: list of (addr, size)."""
        out = []
        pos = self.off_rsvmap
        while True:
            addr, size = struct.unpack_from('>QQ', self.blob, pos)
            pos += 16
            if addr == 0 and size == 0:
                break
            out.append((addr, size))
        return out

    def walk(self):
        """Yield (depth, node_path, name, props) for every node, depth first.

        props maps property name -> bytes value.
        """
        pos = self.off_struct
        path = []
        while True:
            tok = _u32(self.blob, pos)
            pos += 4
            if tok == FDT_BEGIN_NODE:
                end = self.blob.index(b'\0', pos)
                name = self.blob[pos:end].decode('utf-8', 'replace')
                pos = (end + 4) & ~3
                path.append(name)
                yield len(path) - 1, self._join(path), name, None
            elif tok == FDT_END_NODE:
                if path:
                    path.pop()
            elif tok == FDT_PROP:
                length, nameoff = struct.unpack_from('>II', self.blob, pos)
                pos += 8
                value = self.blob[pos:pos + length]
                pos = (pos + length + 3) & ~3
                yield len(path) - 1, self._join(path), self._string(nameoff), value
            elif tok == FDT_NOP:
                continue
            elif tok == FDT_END:
                break
            else:
                raise ValueError('bad FDT token %d at %d' % (tok, pos - 4))

    def nodes(self):
        """Return {path: {prop: value}} for all nodes."""
        out = {}
        for _depth, path, name, props in self.walk():
            if props is not None:
                out.setdefault(path, {})[name] = props
        return out


class DTBO:
    """Android dt_table (mkdtimg) container."""

    def __init__(self, blob):
        if _u32(blob, 0) != DTBO_MAGIC:
            raise ValueError('not a dt_table image (bad magic)')
        self.blob = blob
        self.total_size = _u32(blob, 4)
        self.header_size = _u32(blob, 8)
        self.entry_size = _u32(blob, 12)
        self.entry_count = _u32(blob, 16)
        self.entries_offset = _u32(blob, 20)
        self.page_size = _u32(blob, 24)
        self.version = _u32(blob, 28)

    def entries(self):
        """Yield dicts describing each embedded DTB."""
        for i in range(self.entry_count):
            off = self.entries_offset + i * self.entry_size
            dt_size, dt_offset = struct.unpack_from('>II', self.blob, off)
            ident, rev = struct.unpack_from('>II', self.blob, off + 8)
            custom = struct.unpack_from('>4I', self.blob, off + 16)
            yield {
                'index': i,
                'size': dt_size,
                'offset': dt_offset,
                'id': ident,
                'rev': rev,
                'custom': custom,
                'blob': self.blob[dt_offset:dt_offset + dt_size],
            }


def scan_for_fdt(blob, limit=40):
    """Find every 0xd00dfeed offset in a blob (for images with appended DTBs)."""
    hits = []
    start = 0
    while len(hits) < limit:
        i = blob.find(b'\xd0\x0d\xfe\xed', start)
        if i < 0:
            break
        try:
            size = _u32(blob, i + 4)
            if 0 < size <= len(blob) - i:
                hits.append((i, size, FDT(blob[i:i + size])))
                start = i + 4
            else:
                start = i + 4
        except Exception:
            start = i + 4
    return hits


def load_entries(path):
    """Return a list of (label, blob) for a DTB or DTBO file."""
    blob = open(path, 'rb').read()
    if len(blob) >= 4 and _u32(blob, 0) == DTBO_MAGIC:
        return [('entry%d' % e['index'], e['blob']) for e in DTBO(blob).entries()], blob
    if len(blob) >= 4 and _u32(blob, 0) == FDT_MAGIC:
        return [('dtb', blob[:FDT(blob).totalsize])], blob
    return [], blob


def fmt_bytes(v):
    if len(v) == 4:
        return str(struct.unpack('>I', v)[0])
    if len(v) == 8:
        return str(struct.unpack('>Q', v)[0])
    if len(v) % 4 == 0 and len(v) <= 32:
        return ' '.join('<%08x>' % x for x in struct.unpack('>%dI' % (len(v) // 4), v))
    if all(32 <= c < 127 or c == 0 for c in v):
        return repr(v.rstrip(b'\0').decode('ascii', 'replace'))
    return v.hex()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('file')
    ap.add_argument('--list', action='store_true', help='list DTBs in the container')
    ap.add_argument('--entry', type=int, help='which DTB to inspect')
    ap.add_argument('--scan', action='store_true', help='scan for FDT magic offsets')
    ap.add_argument('--find', help='print nodes/props whose path matches this regex')
    ap.add_argument('--resmem', action='store_true', help='decode reserved-memory')
    ap.add_argument('--projects', action='store_true', help='show devinfo/model markers')
    args = ap.parse_args()

    blob = open(args.file, 'rb').read()

    if args.scan:
        for off, size, fdt in scan_for_fdt(blob):
            print('FDT at 0x%08x  size=%d  version=%d' % (off, size, fdt.version))
        return

    entries, _ = load_entries(args.file)
    is_dtbo = len(blob) >= 4 and _u32(blob, 0) == DTBO_MAGIC

    if args.list:
        if not is_dtbo:
            print('plain DTB, not a dt_table container')
            return
        d = DTBO(blob)
        print('dt_table: %d entries, header=%d entry_size=%d page=%d version=%d'
              % (d.entry_count, d.header_size, d.entry_size, d.page_size, d.version))
        for e in DTBO(blob).entries():
            print('  entry %d: id=0x%08x rev=0x%08x size=%-8d off=%-10d custom=%s'
                  % (e['index'], e['id'], e['rev'], e['size'], e['offset'],
                     ' '.join('0x%x' % c for c in e['custom'])))
        return

    if not entries:
        sys.exit('no DTB found in %s' % args.file)

    if args.entry is None:
        args.entry = 0
    label, sub = entries[args.entry]
    fdt = FDT(sub)
    print('== %s :: %s (version %d, %d bytes)' % (args.file, label, fdt.version, len(sub)))

    if args.projects:
        import re
        pat = re.compile(r'devinfo|qcom,model|^/model|qcom,board-id|kalama')
        seen = set()
        for _d, path, name, props in fdt.walk():
            if props is None:
                if pat.search(name) and name not in seen:
                    seen.add(name)
                    print('  node   %s' % path)
            elif path.endswith('devinfo') or name == 'compatible' or name == 'model':
                if pat.search(path) or name in ('compatible', 'model'):
                    print('  %-60s %s = %s' % (path, name, fmt_bytes(props)))
        return

    if args.resmem:
        nodes = fdt.nodes()
        total = 0
        print('-- reserve map (flat) --')
        for addr, size in fdt.reserved_memory():
            print('  0x%016x - 0x%016x  (%d MiB)' % (addr, addr + size, size >> 20))
        print('-- reserved-memory nodes --')
        for path, props in sorted(nodes.items()):
            if '/reserved-memory/' in path + '/' and 'reg' in props:
                v = props['reg']
                if len(v) == 16:
                    base, size = struct.unpack('>QQ', v)
                    total += size
                    print('  %-58s 0x%010x + %6d KiB' % (path.split('/')[-1], base, size >> 10))
                else:
                    print('  %-58s reg=%s' % (path.split('/')[-1], fmt_bytes(v)))
        print('  total reserved: %d MiB' % (total >> 20))
        return

    if args.find:
        import re
        pat = re.compile(args.find)
        for _d, path, name, props in fdt.walk():
            if props is None:
                if pat.search(path):
                    print('\n[%s]' % path)
            elif pat.search(path) or pat.search(name):
                print('    %s = %s' % (name, fmt_bytes(props)))
        return

    # default: brief overview
    nodes = fdt.nodes()
    print('%d nodes' % len(nodes))
    top = sorted({p.split('/')[1] for p in nodes if len(p.split('/')) > 1})
    print('top-level: %s' % ', '.join(top[:40]))


if __name__ == '__main__':
    main()
