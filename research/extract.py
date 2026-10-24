#!/usr/bin/env python3
"""Extract exact node blocks from a DTS by node name (brace matched)."""
import re, sys

path, pattern = sys.argv[1], sys.argv[2]
with open(path, encoding='utf-8') as f:
    src = f.read()
src = re.sub(r'/\*.*?\*/', lambda m: '\n' * m.group(0).count('\n'), src, flags=re.S)
lines = src.split('\n')

decl = re.compile(r'^\s*(?:([A-Za-z0-9_\-]+)\s*:\s*)?([A-Za-z0-9_][A-Za-z0-9_@,\-\.\+]*)\s*\{\s*$')
want = re.compile(pattern)

for i, l in enumerate(lines):
    code = re.sub(r'//.*', '', l).rstrip()
    m = decl.match(code)
    if not m:
        continue
    label, name = m.group(1), m.group(2)
    if not want.search(name) and not (label and want.search(label)):
        continue
    # brace match
    depth = code.count('{') - code.count('}')
    j = i
    while depth > 0 and j + 1 < len(lines):
        j += 1
        c2 = re.sub(r'//.*', '', lines[j])
        depth += c2.count('{') - c2.count('}')
    print(f"--- {name}  (label={label}, L{i+1}-{j+1}) ---")
    for k in range(i, min(j + 1, i + 46)):
        print(f"{k+1}: {lines[k]}")
    print()
