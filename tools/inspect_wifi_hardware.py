"""Resolve stock/live Wi-Fi properties and regulator references offline."""
from pathlib import Path
import json
import struct
import tarfile
from fdt import FDT

out = Path('out/wifi-bringup-20261017')
sources = {}
for name in ['reference/live-PJA110-A14-16G.dtb', 'live-from-device.dtb',
             'out/native-install-20261017/adc-gen3/adc-added.dtb']:
    path = Path(name)
    if path.exists():
        sources[name] = FDT(path.read_bytes()).nodes()
archive = out / 'live-devicetree.tar'
if archive.exists() and archive.stat().st_size:
    nodes = {}
    with tarfile.open(archive) as tf:
        for m in tf:
            name = '/' + m.name.removeprefix('./').rstrip('/')
            if m.isdir():
                nodes.setdefault(name, {})
            elif m.isfile():
                parent, _, prop = name.rpartition('/')
                nodes.setdefault(parent or '/', {})[prop] = tf.extractfile(m).read()
    sources['live'] = nodes
report = {}
for source, nodes in sources.items():
    phandles = {struct.unpack('>I', p['phandle'])[0]: (n, p)
                for n, p in nodes.items() if len(p.get('phandle', b'')) == 4}
    result = {}
    for node, props in nodes.items():
        if not any(s in node.lower() for s in ['wlan', 'wcn', 'cnss', 'pcie', 'sleep-clk']):
            continue
        selected = {}
        for key, value in props.items():
            if len(value) > 180:
                continue
            if value and value.endswith(b'\0') and all(c == 0 or 32 <= c < 127 for c in value):
                decoded = value.rstrip(b'\0').decode().replace('\0', '|')
            else:
                decoded = value.hex()
            selected[key] = decoded
            if key.endswith('-supply') and len(value) == 4:
                ref = phandles.get(struct.unpack('>I', value)[0])
                if ref:
                    selected[key + ':resolved'] = dict(node=ref[0], properties={
                        k: v.hex() for k, v in ref[1].items()
                        if k in ['regulator-name', 'regulator-min-microvolt', 'regulator-max-microvolt']})
        result[node] = selected
    report[source] = result
(out / 'hardware.json').write_text(json.dumps(report, indent=2) + '\n')
for source, nodes in report.items():
    print('SOURCE', source)
    for node, props in nodes.items():
        if any(k.endswith('-supply') or 'gpio' in k for k in props) or node.endswith(('pcie@1c00000', 'phy@1c06000')):
            print(node, json.dumps({k: v for k, v in props.items()
                                    if k in ['compatible', 'status', 'perst-gpio', 'wake-gpio', 'wlan-en-gpio']
                                    or k.endswith('-supply:resolved') or 'enable-gpio' in k}))
