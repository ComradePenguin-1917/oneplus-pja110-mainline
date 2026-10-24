#!/usr/bin/env python3
"""
Robust DTS node inventory using explicit indentation depth (kernel = tabs).
Nodes at depth D end when a line at depth <= D that is not a continuation appears.
"""
import re, sys

path = sys.argv[1]
maxdepth = int(sys.argv[2]) if len(sys.argv) > 2 else 1
pat = sys.argv[3] if len(sys.argv) > 3 else None

with open(path, encoding='utf-8') as f:
    raw = f.read()
raw = re.sub(r'/\*.*?\*/', lambda m: '\n' * m.group(0).count('\n'), raw, flags=re.S)
lines = raw.split('\n')

def depth_of(s):
    n = 0
    for ch in s:
        if ch == '\t':
            n += 1
        elif ch == ' ':
            n += 1  # treat 8 spaces as ~1 level; kernel uses tabs
        else:
            break
    return n

NODE = re.compile(r'^(\t*)(?:([A-Za-z0-9_\-]+)\s*:\s*)?([A-Za-z0-9_][A-Za-z0-9_@,\-\.\+]*)\s*\{(.*)$')

# Pass 1: locate all node declarations with their depth and line
decls = []   # (depth, name, lineno)
for idx, l in enumerate(lines):
    code = re.sub(r'//.*', '', l)
    m = NODE.match(code)
    if m:
        # exclude property assignment lines like 'foo = <&bar {' -- require no '=' before '{'
        before = code[:code.index('{')]
        if '=' in before:
            continue
        d = len(m.group(1))
        decls.append((d, m.group(3), idx))

# Pass 2: for each decl, body = lines until the matching close at same depth
records = []
for k, (d, name, idx) in enumerate(decls):
    # find end: first following line whose depth <= d and is '};' or a new decl at depth <= d
    end = idx
    j = idx + 1
    while j < len(lines):
        code = re.sub(r'//.*', '', lines[j])
        if code.strip() == '':
            j += 1
            continue
        dd = depth_of(code)
        if dd <= d:
            break
        j += 1
    end = j
    body = '\n'.join(lines[idx:end])
    # parent: nearest preceding decl with smaller depth
    parent = None
    for pd, pname, pidx in reversed(decls[:k]):
        if pd < d:
            parent = pname
            break
    records.append((d, name, idx + 1, body, parent))

print(f"FILE: {path}  node decls={len(records)}")
print()
for d, name, ln, body, parent in records:
    if d > maxdepth:
        continue
    cs = []
    for mm in re.finditer(r'compatible\s*=\s*((?:"[^"]*"\s*,?\s*)+)', body):
        cs.extend(re.findall(r'"([^"]*)"', mm.group(1)))
    st = re.search(r'\bstatus\s*=\s*"([^"]*)"', body)
    stv = st.group(1) if st else None
    hay = (name + ' ' + ' '.join(cs)).lower()
    if pat and pat.lower() not in hay:
        continue
    ind = '  ' * d
    tag = f'  [status={stv}]' if stv else ''
    print(f"{ind}{name}{tag}   (L{ln}, parent={parent})")
    if cs:
        print(f"{ind}    compat: {' | '.join(cs[:4])}")
