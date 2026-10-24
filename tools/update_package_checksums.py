"""Refresh local APKBUILD ``sha512sums`` from the authoritative package sources.

The project keeps its package recipes in ``postmarketos/`` on Windows and only
derives WSL/pmaports copies at build time.  This tool rewrites the checksum
lines in place, keeps LF line endings, and refuses to invent a checksum for a
source file that does not exist.
"""
import argparse
import hashlib
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = [
    'device/testing/device-oneplus-xigua',
    'device/testing/linux-oneplus-xigua',
    'device/testing/firmware-oneplus-xigua-adreno',
    'device/testing/firmware-oneplus-xigua-adsp',
    'device/testing/firmware-oneplus-xigua-wifi',
    'main/phoc',
]
LINE = re.compile(r'^([0-9a-f]{128})  (\S+)$')


def declared_sources(text):
    """Names listed in the ``source="..."`` block, in order."""
    lines = text.split('\n')
    block = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped.startswith('source="'):
            continue
        rest = stripped[len('source="'):]
        if '"' in rest:
            block = rest.split('"', 1)[0]
        else:
            parts = [rest]
            for nxt in lines[i + 1:]:
                if nxt.strip() == '"':
                    break
                parts.append(nxt.strip())
            block = ' '.join(parts)
        break
    if block is None:
        return []
    names = []
    for token in block.split():
        name = token.split('::', 1)[0]
        if not name or name.startswith('-') or '$' in name:
            continue
        names.append(name)
    return names


def refresh(recipe_path):
    text = recipe_path.read_bytes().decode('utf-8')
    assert '\r\n' not in text, f'{recipe_path}: CRLF'
    sources = declared_sources(text)
    lines = text.split('\n')
    out = []
    changed = False
    present = set()
    for line in lines:
        m = LINE.match(line)
        if not m:
            out.append(line)
            continue
        name = m.group(2)
        source = recipe_path.parent / name
        if not source.is_file():
            # Upstream tarballs are fetched by pmbootstrap; their pinned digest
            # stays as recorded and must not be recomputed here.
            if name.endswith(('.tar.xz', '.tar.gz', '.tar.bz2', '.tar.zst')):
                out.append(line)
                continue
            raise SystemExit(f'{recipe_path}: missing source {name}')
        present.add(name)
        digest = hashlib.sha512(source.read_bytes()).hexdigest()
        new = f'{digest}  {name}'
        changed |= new != line
        out.append(new)
    # Every explicitly declared source must have a checksum line.
    unchecksummed = [n for n in sources
                     if n not in present
                     and not n.endswith(('.tar.xz', '.tar.gz', '.tar.bz2', '.tar.zst'))]
    if changed:
        recipe_path.write_bytes('\n'.join(out).encode('utf-8'))
    return changed, unchecksummed


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--check', action='store_true', help='fail if a refresh is needed')
    args = ap.parse_args()
    dirty = False
    for pkg in PACKAGES:
        recipe = ROOT / 'postmarketos' / pkg / 'APKBUILD'
        changed, missing = refresh(recipe)
        dirty |= changed
        state = 'updated' if changed else 'unchanged'
        print(f'{state:9s} {pkg}')
        if missing:
            print(f'  UNCHECKSUMMED: {", ".join(missing)}')
            dirty = True
    if args.check and dirty:
        raise SystemExit('APKBUILD checksums are out of date')


if __name__ == '__main__':
    main()
