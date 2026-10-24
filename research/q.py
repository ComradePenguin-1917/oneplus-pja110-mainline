#!/usr/bin/env python3
"""
Precise DTS node query tool.
Usage: q.py <file> [--all] [--status] [--label] <regex>
Prints, for every node whose name or label matches <regex>:
  label, name, line, status (own 'status' property), and selected props.
--all prints every node with its status.
"""
import re, sys

args = sys.argv[1:]
path = args[0]
flags = [a for a in args[1:] if a.startswith('--')]
pats = [a for a in args[1:] if not a.startswith('--')]
show_all = '--all' in flags
unlabeled = '--unlabeled' in flags
pat = re.compile(pats[0]) if pats else None

with open(path, encoding='utf-8') as f:
    src = f.read()
src = re.sub(r'/\*.*?\*/', lambda m: '\n' * m.group(0).count('\n'), src, flags=re.S)
lines = src.split('\n')

decl = re.compile(r'^(\s*)(?:([A-Za-z0-9_\-]+)\s*:\s*)?([A-Za-z0-9_][A-Za-z0-9_@,\-\.\+]*)\s*\{\s*$')

rows = []
for i, l in enumerate(lines):
    code = re.sub(r'//.*', '', l).rstrip()
    m = decl.match(code)
    if not m:
        continue
    indent, label, name = len(m.group(1)), m.group(2), m.group(3)
    depth = code.count('{') - code.count('}')
    j = i
    while depth > 0 and j + 1 < len(lines):
        j += 1
        c2 = re.sub(r'//.*', '', lines[j])
        depth += c2.count('{') - c2.count('}')
    body = '\n'.join(lines[i:j+1])
    # own status: first status at node's own property indentation (one deeper than decl)
    st = None
    for bl in body.split('\n'):
        ms = re.match(r'^\s*status\s*=\s*"([^"]*)"', bl)
        if ms:
            st = ms.group(1)
            break
    cs = []
    mc = re.search(r'^\s*compatible\s*=\s*((?:"[^"]*"\s*,?\s*)+)', body, re.M)
    if mc:
        cs = re.findall(r'"([^"]*)"', mc.group(1))
    rows.append(dict(label=label, name=name, line=i+1, status=st, compat=cs,
                     indent=indent, body=body))

if show_all:
    for r in rows:
        if r['indent'] > 16:
            continue
        ind = ' ' * r['indent']
        s = f" [{r['status']}]" if r['status'] else ""
        lb = f"{r['label']}: " if r['label'] else ""
        print(f"{r['line']:>6}  {ind}{lb}{r['name']}{s}")
else:
    for r in rows:
        hay = (r['name'] or '') + ' ' + (r['label'] or '') + ' ' + ' '.join(r['compat'])
        if pat and not pat.search(hay):
            continue
        if unlabeled and r['label']:
            continue
        print(f"L{r['line']}: {r['label'] or '-'} : {r['name']}   status={r['status']}  compat={r['compat']}")
