#!/usr/bin/env python3
"""Parse a mainline Qualcomm SoC dtsi and inventory its top-level nodes."""
import re, sys, json

path = sys.argv[1]
with open(path, encoding='utf-8') as f:
    src = f.read()

# Strip comments
src_nc = re.sub(r'/\*.*?\*/', '', src, flags=re.S)
src_nc = re.sub(r'//[^\n]*', '', src_nc)

lines = src_nc.split('\n')

# Find node declarations at indent level 1 (inside the root / { })
node_re = re.compile(r'^(\t)([A-Za-z0-9_@,\-\.\+]+)\s*\{')
root_depth = None
nodes = []   # (name, startline, endline, body)

i = 0
while i < len(lines):
    line = lines[i]
    m = node_re.match(line)
    if m:
        name = m.group(2)
        # walk forward to matching close brace
        depth = line.count('{') - line.count('}')
        j = i
        while depth > 0 and j + 1 < len(lines):
            j += 1
            depth += lines[j].count('{') - lines[j].count('}')
        body = '\n'.join(lines[i:j+1])
        nodes.append((name, i+1, j+1, body))
        i = j + 1
    else:
        i += 1

print(f"FILE: {path}")
print(f"total lines: {len(lines)}")
print(f"top-level nodes found: {len(nodes)}")
print()

def compat(body):
    out = []
    for m in re.finditer(r'compatible\s*=\s*((?:"[^"]*"\s*,?\s*)+)', body):
        vals = re.findall(r'"([^"]*)"', m.group(1))
        out.extend(vals)
    return out

def status(body):
    m = re.search(r'\bstatus\s*=\s*"([^"]*)"', body)
    return m.group(1) if m else None

# Report
for name, s, e, body in nodes:
    cs = compat(body)
    st = status(body)
    tag = f" [status={st}]" if st else ""
    print(f"{name}{tag}  (L{s}-{e})")
    if cs:
        print(f"    compatible: {' | '.join(cs[:3])}")
