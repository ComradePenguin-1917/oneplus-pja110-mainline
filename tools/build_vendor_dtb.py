"""Rebuild the accepted PJA110 device tree from a pinned source DTS.

The packaged ``verified-vendor.dtb`` used to be an opaque blob.  This tool makes
the generation path explicit and repeatable:

  1. pinned source: ``dtb-source/oneplus-xigua.dts`` (decompiled from the
     accepted Wi-Fi bring-up DTB ``out/wifi-bringup-20261017/wifi-added.dtb``,
     sha256 18cf2a5d...), hash-checked;
  2. explicit, reviewable transformations: ``dtb-source/source-patches.json``
     (currently one fix for dtc's string/octal round-trip on
     ``regulator-min-microvolt`` of bob1);
  3. compile with dtc;
  4. semantic comparison against the packaged fallback blob: same node set and
     same normalised property values (phandles mapped to absolute paths);
  5. machine-readable manifest with every hash and the comparison result.

The blob stays in the package as the rollback reference; this tool does not
overwrite it unless ``--update-package`` is passed explicitly.
"""
import argparse
import hashlib
import json
import re
import shutil
import struct
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / 'postmarketos/device/testing/device-oneplus-xigua'
SOURCE = PKG / 'dtb-source/oneplus-xigua.dts'
PATCHES = PKG / 'dtb-source/source-patches.json'
FALLBACK = PKG / 'verified-vendor.dtb'
DEFAULT_OUT = ROOT / 'out/baseline-20261017/dtb-build'
REQUIRED_NODES = {
    '/soc@0/geniqup@8c0000/i2c@880000/fuel-gauge@55',
    '/soc@0/spmi@c400000/pmic@0/adc@9000',
    '/soc@0/spmi@c400000/pmic@0/adc@9000/channel@74c',
    '/soc@0/pcie@1c00000/pcie@0/wifi@0',
    '/soc@0/display-subsystem@ae00000/dsi@ae94000/panel@0',
    '/soc@0/geniqup@ac0000/spi@a90000/touchscreen@0',
}


def sha_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha(path):
    return sha_bytes(path.read_bytes())


def apply_patches(text, patches):
    applied = []
    for item in patches['replacements']:
        count = text.count(item['old'])
        assert count == 1, (
            f"patch for {item.get('node')} must match exactly once, matched {count}; "
            'the pinned source changed')
        text = text.replace(item['old'], item['new'])
        applied.append({'node': item.get('node'), 'old': item['old'], 'new': item['new']})
    return text, applied


def fdt_nodes(blob):
    from fdt import FDT
    return FDT(blob).nodes()


def printable(value):
    if isinstance(value, bytes):
        if all(32 <= c < 127 or c == 0 for c in value):
            return value.rstrip(b'\0').decode('ascii', 'replace').replace('\0', ',')
        return value.hex()
    return str(value)


def normalise(nodes):
    handles = {}
    for path, props in nodes.items():
        for key in ('phandle', 'linux,phandle'):
            raw = props.get(key)
            if raw and len(raw) == 4:
                handles[struct.unpack('>I', raw)[0]] = path
    out = {}
    for path, props in nodes.items():
        clean = {}
        for name, value in props.items():
            if name in ('phandle', 'linux,phandle'):
                clean[name] = f'<{handles.get(struct.unpack(">I", value)[0], "?")}>'
                continue
            if len(value) and len(value) % 4 == 0 and len(value) <= 256 and name not in ('reg', 'ranges'):
                words = struct.unpack('>%dI' % (len(value) // 4), value)
                if any(w in handles for w in words):
                    clean[name] = ' '.join(f'<{handles[w]}>' if w in handles else f'<0x{w:x}>'
                                           for w in words)
                    continue
            clean[name] = printable(value)
        out[path] = clean
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--source', default=str(SOURCE))
    ap.add_argument('--patches', default=str(PATCHES))
    ap.add_argument('--fallback', default=str(FALLBACK), help='accepted blob to compare with')
    ap.add_argument('--dtc', default='dtc')
    ap.add_argument('--out', default=str(DEFAULT_OUT))
    ap.add_argument('--update-package', action='store_true',
                    help='also replace the packaged blob when semantically equal')
    args = ap.parse_args()

    source = Path(args.source)
    patches_path = Path(args.patches)
    fallback = Path(args.fallback)
    raw = source.read_text()
    patches = json.loads(patches_path.read_text())
    patched, applied = apply_patches(raw, patches)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='pja110-dtb-') as scratch:
        dts = Path(scratch) / 'oneplus-xigua.dts'
        dtb = Path(scratch) / 'oneplus-xigua.dtb'
        dts.write_text(patched)
        p = subprocess.run([args.dtc, '-I', 'dts', '-O', 'dtb', '-o', str(dtb), str(dts)],
                           capture_output=True, text=True)
        (out / 'dtc.log').write_text(p.stdout + p.stderr)
        assert p.returncode == 0, f'dtc failed; see {out / "dtc.log"}'
        blob = dtb.read_bytes()

    nodes = fdt_nodes(blob)
    fallback_blob = fallback.read_bytes()
    fallback_nodes = fdt_nodes(fallback_blob)

    missing = sorted(REQUIRED_NODES - set(nodes))
    assert not missing, f'generated DTB lacks required nodes: {missing}'
    compat = nodes.get('/', {}).get('compatible', b'').split(b'\0')
    assert compat[:2] == [b'oneplus,xigua', b'qcom,sm8550'], compat[:2]

    norm_new = normalise(nodes)
    norm_ref = normalise(fallback_nodes)
    only_new = sorted(set(norm_new) - set(norm_ref))
    only_ref = sorted(set(norm_ref) - set(norm_new))
    changed = {}
    for path in sorted(set(norm_new) & set(norm_ref)):
        props = {k: {'generated': norm_new[path].get(k), 'fallback': norm_ref[path].get(k)}
                 for k in sorted(set(norm_new[path]) | set(norm_ref[path]))
                 if norm_new[path].get(k) != norm_ref[path].get(k)}
        if props:
            changed[path] = props
    semantic_equal = not only_new and not only_ref and not changed

    target = out / 'oneplus-xigua.dtb'
    target.write_bytes(blob)
    manifest = {
        'source': {'path': str(source), 'sha256': sha(source), 'bytes': source.stat().st_size},
        'patches': {'path': str(patches_path), 'sha256': sha(patches_path),
                    'applied': applied},
        'dtc': {'command': args.dtc,
                'version': subprocess.run([args.dtc, '--version'],
                                          capture_output=True, text=True).stdout.strip()},
        'output': {'path': str(target), 'sha256': sha(target), 'bytes': len(blob)},
        'fallback': {'path': str(fallback), 'sha256': sha(fallback),
                     'bytes': len(fallback_blob),
                     'byte_identical': blob == fallback_blob},
        'nodes': {'generated': len(nodes), 'fallback': len(fallback_nodes)},
        'semantic_equal': semantic_equal,
        'only_in_generated': only_new,
        'only_in_fallback': only_ref,
        'changed_properties': changed,
        'required_nodes_present': True,
        'package_blob_updated': False,
    }
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps({k: manifest[k] for k in
                      ('source', 'output', 'fallback', 'nodes', 'semantic_equal',
                       'changed_properties')}, indent=2))
    assert semantic_equal, 'generated DTB differs semantically from the fallback blob'
    if args.update_package:
        shutil.copyfile(target, fallback)
        manifest['package_blob_updated'] = True
        (out / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
        print(f'updated packaged blob: {fallback}')
    print('PASS: DTB rebuilt from the pinned source and matches the packaged fallback')


if __name__ == '__main__':
    main()
