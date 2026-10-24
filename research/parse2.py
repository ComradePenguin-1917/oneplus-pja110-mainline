#!/usr/bin/env python3
"""Inventory nodes in a mainline Qualcomm SoC dtsi: report node path + compatible + status."""
import re, sys

path = sys.argv[1]
maxdepth = int(sys.argv[2]) if len(sys.argv) > 2 else 1

with open(path, encoding='utf-8') as f:
    src = f.read()

src = re.sub(r'/\*.*?\*/', lambda m: '\n' * m.group(0).count('\n'), src, flags=re.S)
src = re.sub(r'//[^\n]*', '', src)
lines = src.split('\n')

node_re = re.compile(r'^(\s*)([A-Za-z0-9_@,\-\.\+]+)\s*\{\s*$')

results = []
stack = []  # (depth, name)
i = 0
while i < len(lines):
    line = lines[i]
    m = node_re.match(line)
    if m:
        indent = len(m.group(1).expandtabs(8))
        name = m.group(2)
        depth = indent // 8
        # find matching closing brace
        d = line.count('{') - line.count('}')
        j = i
        while d > 0 and j + 1 < len(lines):
            j += 1
            d += lines[j].count('{') - lines[j].count('}')
        body = '\n'.join(lines[i:j+1])
        cs = []
        for mm in re.finditer(r'compatible\s*=\s*((?:"[^"]*"\s*,?\s*)+)', body):
            cs.extend(re.findall(r'"([^"]*)"', mm.group(1)))
        st = re.search(r'\bstatus\s*=\s*"([^"]*)"', body)
        st = st.group(1) if st else None
        results.append((depth, name, cs, st, i+1, j+1))
        i = j + 1
    else:
        i += 1

print(f"FILE: {path}  ({len(lines)} lines)")
print()
for depth, name, cs, st, s, e in results:
    if depth > maxdepth:
        continue
    ind = '  ' * depth
    tag = f'  status={st}' if st else ''
    print(f"{ind}{name}{tag}   (L{s})")
    if cs:
        print(f"{ind}    compat: {' | '.join(cs[:3])}")
