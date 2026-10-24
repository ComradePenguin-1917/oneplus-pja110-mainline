"""Read the faulting PC and library map from a Linux aarch64 ELF core file.

No binutils/gdb on the target, so this parses the notes directly:
  NT_PRSTATUS -> signal number and the user_regs struct (pc = regs[32])
  NT_FILE     -> mapped file ranges, used to attribute the PC to a library

Usage: python3 core_pc.py <core> [--maps]
"""
import struct
import sys

NT_PRSTATUS = 1
NT_FILE = 0x46494C45  # "FILE"
NT_SIGINFO = 0x53494749


def parse_notes(blob, offset, size):
    """Yield (type, name, desc) notes from a PT_NOTE segment."""
    end = offset + size
    pos = offset
    while pos + 12 <= end:
        namesz, descsz, ntype = struct.unpack_from('<III', blob, pos)
        pos += 12
        name = blob[pos:pos + namesz].rstrip(b'\x00').decode('ascii', 'replace')
        pos += (namesz + 3) & ~3
        desc = blob[pos:pos + descsz]
        pos += (descsz + 3) & ~3
        if not descsz and not ntype:
            break
        yield ntype, name, desc


def main():
    path = sys.argv[1]
    show_maps = '--maps' in sys.argv
    blob = open(path, 'rb').read()

    if blob[:4] != b'\x7fELF':
        raise SystemExit('not an ELF file')
    if blob[4] != 2 or blob[5] != 1:
        raise SystemExit('expected ELF64 little-endian')

    e_phoff, = struct.unpack_from('<Q', blob, 0x20)
    e_phentsize, e_phnum = struct.unpack_from('<HH', blob, 0x36)

    notes = []
    for i in range(e_phnum):
        base = e_phoff + i * e_phentsize
        p_type, = struct.unpack_from('<I', blob, base)
        if p_type != 4:  # PT_NOTE
            continue
        p_offset, = struct.unpack_from('<Q', blob, base + 8)
        p_filesz, = struct.unpack_from('<Q', blob, base + 32)
        notes.extend(parse_notes(blob, p_offset, p_filesz))

    prstatus = [d for t, _, d in notes if t == NT_PRSTATUS]
    if not prstatus:
        raise SystemExit('no NT_PRSTATUS note found')

    desc = prstatus[0]
    si_signo, si_code, si_errno = struct.unpack_from('<iii', desc, 0)
    # struct elf_prstatus: pr_info(12) pr_cursig(2) pad(2) pr_sigpend(8)
    # pr_sighold(8) pr_pid(4) pr_ppid(4) pr_pgrp(4) pr_sid(4) then pr_reg.
    reg_off = 112
    regs = struct.unpack_from('<34Q', desc, reg_off)

    print(f'signal      : {si_signo}  code={si_code}')
    print(f'pc          : 0x{regs[32]:016x}')
    print(f'sp          : 0x{regs[31]:016x}')
    print(f'x0..x3      : {[hex(r) for r in regs[0:4]]}')

    files = [d for t, _, d in notes if t == NT_FILE]
    if not files:
        print('no NT_FILE note; cannot attribute the pc')
        return
    data = files[0]
    count, pagesz = struct.unpack_from('<QQ', data, 0)
    entries = []
    off = 16
    for _ in range(count):
        start, end, pgoff = struct.unpack_from('<QQQ', data, off)
        off += 24
        entries.append([start, end, pgoff, None])
    names = data[off:].split(b'\x00')
    for e, nm in zip(entries, names):
        e[3] = nm.decode('utf-8', 'replace')

    pc = regs[32]
    hit = None
    for start, end, pgoff, name in entries:
        if start <= pc < end:
            hit = (start, end, pgoff, name)
            break
    if hit:
        start, end, pgoff, name = hit
        print(f'faulting in : {name}')
        print(f'  map 0x{start:x}-0x{end:x} pgoff=0x{pgoff:x}')
        print(f'  offset in file: 0x{pc - start + pgoff:x}')
    else:
        print('pc not inside any mapped file (anonymous or JIT page)')
        for start, end, pgoff, name in entries:
            if start <= pc < end:
                print('  range hit but unnamed')

    if show_maps:
        print('\nmaps:')
        for start, end, pgoff, name in entries:
            mark = ' <== pc' if start <= pc < end else ''
            print(f'  0x{start:012x}-0x{end:012x} {name}{mark}')


if __name__ == '__main__':
    main()
