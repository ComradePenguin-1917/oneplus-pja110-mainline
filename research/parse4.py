#!/usr/bin/env python3
"""
Indentation-based node inventory for kernel DTS files.
Kernel DTS style: root children are at one tab, grandchildren at two tabs, properties
one tab deeper than their node. This is reliable for arch/arm64/boot/dts/qcom/.
"""
import re, sys

path = sys.argv[1]
maxdepth = int(sys.argv[2]) if len(sys.argv) > 2 else 1
pat = sys.argv[3] if len(sys.argv) > 3 else None

with open(path, encoding='utf-8') as f:
    raw = f.read()
# blank out block comments but keep line count
raw = re.sub(r'/\*.*?\*/', lambda m: '\n' * m.group(0).count('\n'), raw, flags=re.S)

lines = raw.split('\n')
# determine indentation unit from first indented line
unit = None
for l in lines:
    if l.strip() and l[:1] in ('\t', ' '):
        unit = '\t' if l[:1] == '\t' else '    '
        break
unit = unit or '\t'

node_open = re.compile(r'^(\s*)([A-Za-z0-9_][A-Za-z0-9_@,\-\.\+]*)\s*\{')

records = []
open_stack = []   # (indent_level, name, line, buf)
pending = []      # lines of current property text

def flush(endline):
    """close nodes whose body ended: handled explicitly."""
    pass

i = 0
while i < len(lines):
    line = lines[i]
    stripped = re.sub(r'//.*', '', line).strip()
    if not stripped:
        i += 1
        continue
    indent = len(line) - len(line.lstrip(unit[0])) if line[:1] == unit[0] else 0
    ind_level = indent // len(unit)

    m = node_open.match(re.sub(r'//.*', '', line))
    if m:
        # close any open node at ind_level >= this one
        while open_stack and open_stack[-1][0] >= ind_level:
            lvl, nm, ln, buf, parent = open_stack.pop()
            records.append((lvl, nm, ln, '\n'.join(buf), parent))
        parent = open_stack[-1][1] if open_stack else None
        open_stack.append((ind_level, m.group(2), i + 1, [], parent))
        i += 1
        continue

    # property line
    if open_stack:
        open_stack[-1][3].append(stripped)
    i += 1

while open_stack:
    lvl, nm, ln, buf, parent = open_stack.pop()
    records.append((lvl, nm, ln, '\n'.join(buf), parent))

records.sort(key=lambda r: r[2])

print(f"FILE: {path}  nodes={len(records)}  unit={repr(unit)}")
print()
for lvl, nm, ln, body, parent in records:
    if lvl > maxdepth:
        continue
    cs = []
    for mm in re.finditer(r'compatible\s*=\s*((?:"[^"]*"\s*,?\s*)+)', body):
        cs.extend(re.findall(r'"([^"]*)"', mm.group(1)))
    st = re.search(r'\bstatus\s*=\s*"([^"]*)"', body)
    stv = st.group(1) if st else None
    hay = (nm + ' ' + ' '.join(cs)).lower()
    if pat and pat.lower() not in hay:
        continue
    ind = '  ' * lvl
    tag = f'  status={stv}' if stv else ''
    print(f"{ind}{nm}{tag}   (L{ln})")
    if cs:
        print(f"{ind}    compat: {' | '.join(cs[:4])}")
