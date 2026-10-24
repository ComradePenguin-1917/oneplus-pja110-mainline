#!/usr/bin/env python3
"""Brace-stack node inventory for mainline Qualcomm dtsi files."""
import re, sys

path = sys.argv[1]
maxdepth = int(sys.argv[2]) if len(sys.argv) > 2 else 1
want = sys.argv[3] if len(sys.argv) > 3 else None

with open(path, encoding='utf-8') as f:
    src = f.read()
src = re.sub(r'/\*.*?\*/', lambda m: '\n' * m.group(0).count('\n'), src, flags=re.S)

out = []
stack = []          # list of open brace entries: dict(kind, name, depth, line, buf)
root_children = []
allnodes = {}       # (path) -> node record

for lineno, raw in enumerate(src.split('\n'), 1):
    line = re.sub(r'//.*', '', raw)
    stripped = line.strip()
    if not stripped:
        continue
    lbrace = line.count('{')
    rbrace = line.count('}')

    if lbrace and not stack:
        # root: '/ {', '&label {', '/dts-v1/;' etc.
        m = re.match(r'^\s*(&?[A-Za-z0-9_\-]+)\s*\{', line) or re.match(r'^\s*(/)\s*\{', line)
        name = m.group(1) if m else '<anon-root>'
        stack.append({'kind': 'root', 'name': name, 'depth': 0, 'line': lineno, 'buf': []})
        # handle inline close
        for _ in range(rbrace - (lbrace - 1)):
            if stack: stack.pop()
        continue

    if stack:
        depth = stack[-1]['depth'] + 1
    else:
        depth = 0

    # node declaration: NAME { possibly with @addr
    m = re.match(r'^\s*([A-Za-z0-9_][A-Za-z0-9_@,\-\.\+]*)\s*\{', line)
    if m and stack:
        name = m.group(1)
        stack.append({'kind': 'node', 'name': name, 'depth': depth, 'line': lineno,
                      'parent': stack[-1]['name'], 'buf': []})
        net = lbrace - rbrace
        for _ in range(net):
            stack.pop()
        continue

    # accumulate property text into current node buffers
    prop = stripped
    for e in stack:
        e['buf'].append(prop)

    net = lbrace - rbrace
    if net < 0:
        for _ in range(-net):
            if len(stack) > 1:
                e = stack.pop()
                body = ' | '.join(e['buf'])
                cs = re.findall(r'compatible\s*=\s*((?:"[^"]*"\s*,?\s*)+)', body)
                csl = []
                for c in cs:
                    csl.extend(re.findall(r'"([^"]*)"', c))
                st = re.search(r'status\s*=\s*"([^"]*)"', body)
                allnodes[(e['parent'], e['name'], e['line'])] = (e['depth'], e['name'], csl, st.group(1) if st else None, e['line'], e['parent'])
            elif len(stack) == 1:
                stack.pop()
    elif net > 0:
        pass

records = sorted(allnodes.values(), key=lambda r: r[4])
print(f"FILE: {path}  nodes={len(records)}")
print()
for depth, name, cs, st, line, parent in records:
    if want and want.lower() not in (name + ' ' + ' '.join(cs)).lower():
        continue
    if depth > maxdepth:
        continue
    ind = '  ' * depth
    tag = f'  status={st}' if st else ''
    print(f"{ind}{name}{tag}   (L{line})")
    if cs:
        print(f"{ind}    compat: {' | '.join(cs[:3])}")
