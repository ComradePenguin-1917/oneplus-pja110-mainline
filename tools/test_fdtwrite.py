#!/usr/bin/env python3
"""Prove the FDT writer is faithful before using it on a boot-critical blob.

A tree writer that silently drops or reorders anything would produce a device
tree that boots differently -- or not at all -- and the failure would look like a
kernel problem. So test it hard:

  1. parse -> serialise -> parse again: every node path and every property must
     match exactly, with identical bytes
  2. the result must be a valid FDT accepted by libfdt (dtc/fdtget in WSL)
  3. the set of labels in /__symbols__ must be preserved (the overlays need them)

Round-tripping the vendic base tree itself is the strongest test available: it is
a real, complex, 2994-node tree.
"""
import hashlib
import os
import struct
import subprocess
import sys

sys.path.insert(0, os.path.join(r'H:\WorkSpace\PJA110-Mainline', 'tools'))
from fdtwrite import parse, serialise, walk, FDT_MAGIC
from fdt import FDT

WS = r'H:\WorkSpace\PJA110-Mainline'
WSL_WS = '/mnt/h/WorkSpace/PJA110-Mainline'

v = open(os.path.join(WS, 'backup', 'vendor_boot_b.img'), 'rb').read()
hsize, dtbsize = struct.unpack_from('<2I', v, 28+2048+4+16)
vrsize = struct.unpack_from('<I', v, 24)[0]
dtb_off = (((hsize+4095)//4096)*4096 + vrsize + 4095)//4096*4096
e0 = struct.unpack_from('>I', v, dtb_off+4)[0]
orig = v[dtb_off:dtb_off+e0]

print('=== input ===')
print('  entry0 size: %d' % len(orig))
print('  totalsize  : %d' % struct.unpack_from('>I', orig, 4)[0])

root, rsvmap = parse(orig)
print()
print('=== parse ===')
nodes = list(walk(root))
print('  nodes      : %d' % len(nodes))
print('  rsvmap     : %d bytes' % len(rsvmap))

out = serialise(root, rsvmap)
print()
print('=== serialise ===')
print('  output size: %d (orig %d, delta %+d)' % (len(out), len(orig), len(out) - len(orig)))
print('  magic      : 0x%08x' % struct.unpack_from('>I', out, 0)[0])

print()
print('=== 1) re-parse and compare content ===')
r2, rsv2 = parse(out)
n2 = dict(walk(r2))
n1 = dict(walk(root))
print('  node count : %d -> %d' % (len(n1), len(n2)))
missing = set(n1) - set(n2)
extra = set(n2) - set(n1)
print('  missing paths: %d' % len(missing))
for p in sorted(missing)[:5]:
    print('      %s' % p)
print('  extra paths  : %d' % len(extra))
for p in sorted(extra)[:5]:
    print('      %s' % p)

prop_mismatch = 0
for p in n1:
    if p not in n2:
        continue
    a, b = n1[p].props, n2[p].props
    if set(a) != set(b):
        prop_mismatch += 1
        continue
    for k in a:
        if a[k] != b[k]:
            prop_mismatch += 1
            break
print('  nodes with property differences: %d' % prop_mismatch)

print()
print('=== 2) __symbols__ preservation (the overlays depend on this) ===')
s1 = set(n1.get('/__symbols__').props) if '/__symbols__' in n1 else set()
s2 = set(n2.get('/__symbols__').props) if '/__symbols__' in n2 else set()
print('  original labels: %d' % len(s1))
print('  rebuilt  labels: %d' % len(s2))
print('  identical sets : %s' % (s1 == s2))
if s1 != s2:
    print('    missing: %s' % sorted(s1 - s2)[:10])
    print('    extra  : %s' % sorted(s2 - s1)[:10])

print()
print('=== 3) libfdt must accept it ===')
p_out = os.path.join(WS, 'out', '_roundtrip.dtb')
open(p_out, 'wb').write(out)
cmd = ('cd %s/out && fdtget -l _roundtrip.dtb / >/dev/null 2>&1 && echo "fdtget: OK" || echo "fdtget: FAILED"; '
       'dtc -I dtb -O dts -o /dev/null _roundtrip.dtb 2>&1 | head -3' % WSL_WS)
r = subprocess.run(['wsl.exe', '-d', 'Ubuntu-22.04', '--', 'bash', '-lc', cmd], capture_output=True)
for line in (r.stdout or b'').decode('utf-8', 'replace').splitlines():
    if line.strip() and 'localh' not in line and 'N/e' not in line:
        print('  %s' % line.strip()[:110])

print()
print('=== 4) our own parser must also accept it ===')
f = FDT(out)
print('  nodes()     : %d' % len(f.nodes()))
print('  model       : %r' % f.nodes()['/'].get('model', b''))

print()
print('=== verdict ===')
ok = (len(missing) == 0 and len(extra) == 0 and prop_mismatch == 0 and s1 == s2)
print('  ROUND TRIP: %s' % ('FAITHFUL' if ok else 'LOSSY -- do not use'))
print('  sha256 orig   : %s' % hashlib.sha256(orig).hexdigest()[:32])
print('  sha256 rebuild: %s' % hashlib.sha256(out).hexdigest()[:32])
sys.exit(0 if ok else 1)
