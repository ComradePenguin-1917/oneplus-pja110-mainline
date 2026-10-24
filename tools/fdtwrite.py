#!/usr/bin/env python3
"""A small FDT writer, enough to rebuild a blob after editing properties.

The vendor base tree is packed tight (no in-blob slack), and prepending
compatible strings makes nodes bigger, so in-place patching is not possible.
Instead we parse the whole tree and serialise a fresh one.

Writing a tree writer is worth it here because the alternative -- growing offsets
by hand inside a 500 KB packed structure block -- is where mistakes become
unrecoverable device bricks.

Supported: nested nodes, byte-string properties (as raw values), NOPs dropped,
memory reservation block copied through verbatim.
"""
import struct

FDT_MAGIC = 0xD00DFEED
FDT_BEGIN_NODE = 0x00000001
FDT_END_NODE = 0x00000002
FDT_PROP = 0x00000003
FDT_END = 0x00000009


class Node:
    __slots__ = ('name', 'props', 'children', 'order')

    def __init__(self, name):
        self.name = name
        self.props = {}      # name -> bytes
        self.children = []
        self.order = []      # property insertion order

    def set(self, key, value):
        if key not in self.props:
            self.order.append(key)
        self.props[key] = value

    def get(self, key, default=None):
        return self.props.get(key, default)

    def child(self, name):
        for c in self.children:
            if c.name == name:
                return c
        c = Node(name)
        self.children.append(c)
        return c


def parse(blob):
    """Parse an FDT into (root Node, header fields, rsvmap bytes)."""
    magic, totalsize, off_struct, off_strings, off_rsvmap, version, \
        last_comp, boot_cpuid, size_strings, size_struct = struct.unpack_from('>10I', blob, 0)
    if magic != FDT_MAGIC:
        raise ValueError('not an FDT')

    strings = blob[off_strings:off_strings + size_strings]

    def s(off):
        if off >= len(strings):
            return '<bad>'
        end = strings.index(b'\0', off)
        return strings[off:end].decode('utf-8', 'replace')

    # reservation block up to its terminating zero entry
    p = off_rsvmap
    while True:
        a, b = struct.unpack_from('>QQ', blob, p)
        p += 16
        if a == 0 and b == 0:
            break
    rsvmap = blob[off_rsvmap:p]

    root = None
    stack = []
    pos = off_struct
    while True:
        tok = struct.unpack_from('>I', blob, pos)[0]
        pos += 4
        if tok == FDT_BEGIN_NODE:
            end = blob.index(b'\0', pos)
            name = blob[pos:end].decode('utf-8', 'replace')
            pos = (end + 4) & ~3
            node = Node(name)
            if stack:
                stack[-1].children.append(node)
            else:
                root = node
            stack.append(node)
        elif tok == FDT_END_NODE:
            stack.pop()
        elif tok == FDT_PROP:
            ln, noff = struct.unpack_from('>2I', blob, pos)
            pos += 8
            node = stack[-1]
            node.set(s(noff), blob[pos:pos + ln])
            pos = (pos + ln + 3) & ~3
        elif tok == FDT_END:
            break
        elif tok == 0x00000004:  # FDT_NOP, present in the captured live vendor tree
            continue
        else:
            raise ValueError('bad token 0x%08x at %d' % (tok, pos - 4))
    return root, rsvmap


def serialise(root, rsvmap, version=17, boot_cpuid=0, last_comp=16):
    """Serialise back to an FDT blob."""
    strings = bytearray()
    str_index = {}

    def intern(name):
        if name in str_index:
            return str_index[name]
        off = len(strings)
        strings.extend(name.encode('utf-8') + b'\0')
        str_index[name] = off
        return off

    struct_blk = bytearray()

    def emit(node, is_root):
        struct_blk.extend(struct.pack('>I', FDT_BEGIN_NODE))
        nm = b'' if is_root else node.name.encode('utf-8')
        raw = nm + b'\0'
        struct_blk.extend(raw)
        struct_blk.extend(b'\0' * ((-len(raw)) % 4))
        for key in node.order:
            val = node.props[key]
            struct_blk.extend(struct.pack('>III', FDT_PROP, len(val), intern(key)))
            struct_blk.extend(val)
            struct_blk.extend(b'\0' * ((-len(val)) % 4))
        for c in node.children:
            emit(c, False)
        struct_blk.extend(struct.pack('>I', FDT_END_NODE))

    emit(root, True)
    struct_blk.extend(struct.pack('>I', FDT_END))

    off_rsvmap = 40
    off_struct = (off_rsvmap + len(rsvmap) + 7) & ~7
    off_strings = off_struct + len(struct_blk)
    total = off_strings + len(strings)

    hdr = struct.pack('>10I', FDT_MAGIC, total, off_struct, off_strings,
                      off_rsvmap, version, last_comp, boot_cpuid,
                      len(strings), len(struct_blk))
    out = bytearray(total)
    out[0:40] = hdr
    out[off_rsvmap:off_rsvmap + len(rsvmap)] = rsvmap
    out[off_struct:off_struct + len(struct_blk)] = struct_blk
    out[off_strings:off_strings + len(strings)] = strings
    return bytes(out)


def compatible_list(node):
    v = node.get('compatible')
    if not v:
        return []
    return [x for x in v.rstrip(b'\0').split(b'\0') if x]


def set_compatible(node, entries):
    node.set('compatible', b''.join(e.encode('ascii') + b'\0' for e in entries))


def walk(node, path=''):
    yield path or '/', node
    for c in node.children:
        p = (path + '/' + c.name) if path else '/' + c.name
        yield from walk(c, p)


def find(root, path):
    for p, n in walk(root):
        if p == path:
            return n
    return None
