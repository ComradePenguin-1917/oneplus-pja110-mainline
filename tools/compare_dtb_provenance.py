"""Compare the packaged reference DTB with the DTB inside the accepted slot-A
vendor_boot container, and with a captured running tree.

Produces ``dtb-provenance.json``:

  * packaged reference vs container DTB: node set, normalised property equality
    (phandles mapped to paths), byte equality;
  * running tree (merged by ABL with vendor DTBO + bootloader fixups) vs both,
    limited to the reviewed node/property contracts.

This is the deterministic "where did the DTB come from, and what changed" step
that the baseline plan asks for.
"""
import argparse
import json
import struct
from pathlib import Path

from fdt import DTBO, FDT
from verify_vendor_dtb import CHECKS

ROOT = Path(__file__).resolve().parents[1]
REF = ROOT / 'postmarketos/device/testing/device-oneplus-xigua/verified-vendor.dtb'
CONTAINER = ROOT / 'out/wifi-bringup-20261017/vendor_boot_a-wifi.img'
RUNNING = ROOT / 'out/baseline-20261017/raw/running-device-tree.json'
OUT = ROOT / 'out/baseline-20261017/dtb-provenance.json'


def align(n):
    return (n + 4095) // 4096 * 4096


def container_dtb(path):
    data = path.read_bytes()
    assert data[:8] == b'VNDRBOOT'
    version, page = struct.unpack_from('<II', data, 8)
    assert version == 4 and page == 4096
    rdsize = struct.unpack_from('<I', data, 24)[0]
    hsize, dsize = struct.unpack_from('<II', data, 2096)
    dtboff = align(align(hsize) + rdsize)
    return data[dtboff:dtboff + dsize], dsize


def printable(value):
    if isinstance(value, bytes):
        if all(32 <= c < 127 or c == 0 for c in value):
            return value.rstrip(b'\0').decode('ascii', 'replace').replace('\0', ',')
        return value.hex()
    return str(value)


def phandles(nodes):
    out = {}
    for path, props in nodes.items():
        for key in ('phandle', 'linux,phandle'):
            raw = props.get(key)
            if raw and len(raw) == 4:
                out[struct.unpack('>I', raw)[0]] = path
    return out


def normalise(nodes):
    handles = phandles(nodes)
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


def diff(a, b):
    changed = {}
    for path in sorted(set(a) & set(b)):
        props = {}
        for key in sorted(set(a[path]) | set(b[path])):
            if a[path].get(key) != b[path].get(key):
                props[key] = {'left': a[path].get(key), 'right': b[path].get(key)}
        if props:
            changed[path] = props
    return {
        'only_left': sorted(set(a) - set(b)),
        'only_right': sorted(set(b) - set(a)),
        'changed': changed,
    }


def local_path(value):
    """Accept WSL /mnt/h paths in manifests when running on Windows."""
    value = str(value)
    if value.startswith('/mnt/h/'):
        return Path(ROOT.anchor) / value[len('/mnt/h/'):]
    return Path(value)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--reference', default=str(REF))
    ap.add_argument('--container', default=str(CONTAINER))
    ap.add_argument('--running', default=str(RUNNING))
    ap.add_argument('--dtbo', default=str(ROOT / 'out/native-install-20261016/backup/dtbo_a.img'))
    ap.add_argument('--dtb-build', default=str(ROOT / 'out/baseline-20261017/dtb-build/manifest.json'))
    ap.add_argument('--out', default=str(OUT))
    args = ap.parse_args()

    ref_blob = Path(args.reference).read_bytes()
    ref_nodes = FDT(ref_blob).nodes()
    cont_blob, cont_dsize = container_dtb(Path(args.container))
    cont_nodes = FDT(cont_blob).nodes()

    ref_n = normalise(ref_nodes)
    cont_n = normalise(cont_nodes)
    ref_vs_container = diff(ref_n, cont_n)

    report = {
        'packaged_reference': {
            'path': str(args.reference), 'bytes': len(ref_blob), 'nodes': len(ref_nodes),
        },
        'container': {
            'path': str(args.container), 'dtb_bytes': cont_dsize,
            'dtb_sha256': __import__('hashlib').sha256(cont_blob).hexdigest(),
            'nodes': len(cont_nodes),
            'byte_identical_to_reference': cont_blob == ref_blob,
            'same_node_set': set(ref_nodes) == set(cont_nodes),
        },
        'reference_vs_container': ref_vs_container,
        'reviewed_contract_paths': [
            '/soc@0/geniqup@8c0000/i2c@880000/fuel-gauge@55',
            '/soc@0/spmi@c400000/pmic@0/adc@9000',
            '/soc@0/spmi@c400000/pmic@0/adc@9000/channel@74c',
            '/soc@0/pcie@1c00000/pcie@0/wifi@0',
            '/soc@0/display-subsystem@ae00000/dsi@ae94000/panel@0',
            '/soc@0/geniqup@ac0000/spi@a90000/touchscreen@0',
        ],
        'conclusion': None,
        'phone_writes_performed': False,
    }

    if Path(args.running).is_file():
        running = json.loads(Path(args.running).read_text())
        run_n = {p: {k: v for k, v in props.items()} for p, props in running.items()}
        report['running_capture'] = {
            'path': args.running,
            'nodes': len(running),
            'reference_nodes_present': sum(1 for p in ref_nodes if p in running),
            'extra_nodes': len(set(running) - set(ref_nodes)),
        }

    running = None
    if Path(args.running).is_file():
        running = json.loads(Path(args.running).read_text())

    # Per-contract comparison of the running tree, not just node counts.
    contract = []
    for path, prop, pattern, why in CHECKS:
        ref_value = ref_n.get(path, {}).get(prop)
        run_value = running.get(path, {}).get(prop) if running else None
        if run_value is not None:
            run_value = str(run_value).replace('\\0', ',')
        raw = ref_nodes.get(path, {}).get(prop)
        binary = bool(raw) and len(raw) % 4 == 0 and (
            prop.endswith('-gpios') or prop in
            ('reg', 'interrupts', 'interrupts-extended', 'clocks', 'pinctrl-0',
             'resets', 'phys', 'io-channels', 'power-domains'))
        if binary:
            equal = None
            reason = ('binary phandle/GPIO property: compared by the pattern check in '
                      'tools/verify_vendor_dtb.py, not by text equality')
        else:
            equal = run_value is not None and ref_value is not None and run_value == ref_value
            reason = None if equal else 'text value differs'
        contract.append({'path': path, 'property': prop, 'why': why,
                         'reference': ref_value, 'running': run_value,
                         'equal': equal, 'reason': reason})
    report['reviewed_contracts'] = contract
    report['reviewed_contracts_equal'] = all(c['equal'] is not False for c in contract)
    report['reviewed_contracts_summary'] = {
        'equal': sum(1 for c in contract if c['equal'] is True),
        'binary_pattern_checked': sum(1 for c in contract if c['equal'] is None),
        'mismatch': sum(1 for c in contract if c['equal'] is False),
    }

    # Pinned-source rebuild result, when the DTB build has been run.
    build_manifest = Path(args.dtb_build)
    if build_manifest.is_file():
        bm = json.loads(build_manifest.read_text())
        gen_blob = Path(local_path(bm['output']['path']))
        if gen_blob.is_file():
            gen_nodes = FDT(gen_blob.read_bytes()).nodes()
            gen_n = normalise(gen_nodes)
            gen_vs_ref = diff(gen_n, ref_n)
            report['pinned_source_build'] = {
                'manifest': str(build_manifest),
                'source': bm['source'],
                'patches': bm['patches'],
                'dtc': bm['dtc'],
                'output': bm['output'],
                'node_set_equal': set(gen_nodes) == set(ref_nodes),
                'changed_properties': gen_vs_ref['changed'],
                'semantic_equal_to_reference': (set(gen_nodes) == set(ref_nodes)
                                                and not gen_vs_ref['changed']),
            }

    # Every entry of the DTBO container the image preserves.
    dtbo_path = Path(args.dtbo)
    if dtbo_path.is_file():
        d = DTBO(dtbo_path.read_bytes())
        entries = []
        required = set(report['reviewed_contract_paths'])
        for entry in d.entries():
            nodes = FDT(entry['blob']).nodes()
            entries.append({
                'index': entry['index'], 'id': hex(entry['id']),
                'nodes': len(nodes),
                'has_reviewed_paths': sorted(required & set(nodes)) == sorted(required),
                'model': printable(nodes.get('/', {}).get('model', b'')),
            })
        report['dtbo_container'] = {
            'path': str(dtbo_path),
            'sha256': __import__('hashlib').sha256(dtbo_path.read_bytes()).hexdigest(),
            'entries': entries,
            'note': 'the generator keeps dtbo_a byte-identical to the accepted backup; '
                    'these vendor entries are full DTBs, not fragment overlays, and are '
                    'not rewritten by the offline generator',
        }

    same_nodes = set(ref_nodes) == set(cont_nodes)
    same_props = not ref_vs_container['only_left'] and not ref_vs_container['only_right'] \
        and not ref_vs_container['changed']
    if cont_blob == ref_blob:
        report['conclusion'] = 'container DTB is byte-identical to the packaged reference'
    elif same_nodes and not ref_vs_container['changed']:
        report['conclusion'] = ('container DTB and packaged reference carry the same node set '
                                'and the same effective property values; they differ only in '
                                'serialisation/phandle numbering')
    else:
        report['conclusion'] = ('container DTB differs semantically from the packaged reference; '
                                'the generator records the container hash and refuses to rewrite '
                                'the DTB unless an explicit same-size replacement is supplied')

    out = Path(args.out)
    out.write_bytes((json.dumps(report, indent=2, ensure_ascii=False) + '\n').encode())
    print(json.dumps({k: report[k] for k in ('packaged_reference', 'container')}, indent=2))
    print('reviewed contracts equal:', report.get('reviewed_contracts_equal'))
    print('same_node_set:', same_nodes,
          'changed_nodes:', len(ref_vs_container['changed']),
          'only_left:', len(ref_vs_container['only_left']),
          'only_right:', len(ref_vs_container['only_right']))
    print('conclusion:', report['conclusion'])


if __name__ == '__main__':
    main()
