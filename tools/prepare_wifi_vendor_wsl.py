"""Add Aston/upstream WCN7850 topology to the current ADC vendor_boot, offline."""
from pathlib import Path
import hashlib
import json
import struct
import subprocess
import sys

root = Path('/mnt/h/workspace/PJA110-Mainline')
sys.path.insert(0, str(root / 'tools'))
from fdt import FDT, scan_for_fdt

out = root / 'out/wifi-bringup-20261017'
source = root / 'out/native-install-20261017/adc-gen3/vendor_boot_a-adc.img'
raw = source.read_bytes()
sha = lambda b: hashlib.sha256(b).hexdigest()
assert sha(raw) == '9cbff73044d6bed2d424298b3f1894b786715e185e099121ab55f645934c278d'
align = lambda n: (n + 4095) // 4096 * 4096
rdsize = struct.unpack_from('<I', raw, 24)[0]
hsize, dsize = struct.unpack_from('<II', raw, 2096)
offset = align(align(hsize) + rdsize)
entries = [(o, s, t) for o, s, t in scan_for_fdt(raw[offset:offset+dsize])
           if t.nodes().get('/', {}).get('model') == b'OnePlus Ace 2 Pro\0']
assert len(entries) == 1
off, size, tree = entries[0]
nodes = tree.nodes()
symbols = {k: v.rstrip(b'\0').decode() for k, v in nodes['/__symbols__'].items()}
path = out / 'wifi-added.dtb'
path.write_bytes(raw[offset+off:offset+off+size])
next_phandle = max(struct.unpack('>I', n['phandle'])[0] for n in nodes.values() if 'phandle' in n) + 1
added_phandles = {}

def create(node, phandle=False):
    global next_phandle
    subprocess.run(['fdtput', '-c', str(path), node], check=True)
    if phandle:
        added_phandles[node] = next_phandle
        prop(node, 'phandle', [next_phandle])
        next_phandle += 1
    return node

def prop(node, name, values=None, kind='x'):
    args = ['fdtput', '-t', kind, str(path), node, name]
    if values is not None:
        args += [str(v) if kind == 's' else format(v, 'x') for v in values]
    subprocess.run(args, check=True)

def ph(label):
    return struct.unpack('>I', nodes[symbols[label]]['phandle'])[0]

tlmm = symbols['tlmm']
wlan = create(tlmm + '/wlan-en-state', True)
prop(wlan, 'pins', ['gpio80'], 's')
prop(wlan, 'function', ['gpio'], 's')
prop(wlan, 'drive-strength', [8])
prop(wlan, 'bias-pull-down')
bt = create(tlmm + '/bt-default-state', True)
en = create(bt + '/bt-en-pins')
prop(en, 'pins', ['gpio81'], 's')
prop(en, 'function', ['gpio'], 's')
prop(en, 'drive-strength', [16])
prop(en, 'bias-disable')
sw = create(bt + '/sw-ctrl-pins')
prop(sw, 'pins', ['gpio82'], 's')
prop(sw, 'function', ['gpio'], 's')
prop(sw, 'bias-pull-down')
sleep = create(symbols['pmk8550_gpios'] + '/sleep-clk-state', True)
prop(sleep, 'pins', ['gpio3'], 's')
prop(sleep, 'function', ['func1'], 's')
for name in ['input-disable', 'output-enable', 'bias-disable']:
    prop(sleep, name)
prop(sleep, 'power-source', [0])
pmu = create('/wcn7850-pmu')
prop(pmu, 'compatible', ['qcom,wcn7850-pmu'], 's')
prop(pmu, 'pinctrl-names', ['default'], 's')
prop(pmu, 'pinctrl-0', [added_phandles[p] for p in [wlan, bt, sleep]])
prop(pmu, 'wlan-enable-gpios', [ph('tlmm'), 80, 0])
prop(pmu, 'bt-enable-gpios', [ph('tlmm'), 81, 0])
supplies = dict(vdd='vreg_s5g_0p8', vddio='vreg_l15b_1p8', vddaon='vreg_s2g_0p8',
                vdddig='vreg_s4e_0p9', vddrfa1p2='vreg_s4g_1p3', vddrfa1p8='vreg_s6g_1p8')
for name, label in supplies.items():
    prop(pmu, name + '-supply', [ph(label)])
create(pmu + '/regulators')
names = ['rfa_cmn', 'aon_0p59', 'wlcx_0p8', 'wlmx_0p85', 'btcmx_0p85',
         'rfa_0p8', 'rfa_1p2', 'rfa_1p8', 'pcie_0p9', 'pcie_1p8']
for i, name in enumerate(names):
    node = create(pmu + '/regulators/ldo' + str(i), True)
    prop(node, 'regulator-name', ['vreg_pmu_' + name], 's')
pcie = symbols['pcie0']
prop(pcie, 'wake-gpios', [ph('tlmm'), 96, 0])
prop(pcie, 'perst-gpios', [ph('tlmm'), 94, 1])
prop(pcie, 'pinctrl-names', ['default'], 's')
prop(pcie, 'pinctrl-0', [ph('pcie0_default_state')])
prop(pcie, 'status', ['okay'], 's')
port = pcie + '/pcie@0'
prop(port, 'status', ['okay'], 's')
wifi = create(port + '/wifi@0')
prop(wifi, 'compatible', ['pci17cb,1107'], 's')
prop(wifi, 'reg', [0x10000, 0, 0, 0, 0])
for name, index in [('vddrfacmn', 0), ('vddaon', 1), ('vddwlcx', 2), ('vddwlmx', 3),
                    ('vddrfa0p8', 5), ('vddrfa1p2', 6), ('vddrfa1p8', 7), ('vddpcie0p9', 8), ('vddpcie1p8', 9)]:
    prop(wifi, name + '-supply', [added_phandles[pmu + '/regulators/ldo' + str(index)]])
phy = symbols['pcie0_phy']
prop(phy, 'vdda-phy-supply', [ph('vreg_l1e_0p88')])
prop(phy, 'vdda-pll-supply', [ph('vreg_l3e_1p2')])
prop(phy, 'status', ['okay'], 's')
edited = path.read_bytes()
after = FDT(edited).nodes()
changed = {p: sorted(k for k in set(n) | set(after[p]) if n.get(k) != after[p].get(k))
           for p, n in nodes.items() if after.get(p) != n}
assert set(changed) == {pcie, port, phy}, changed
assert len(edited) <= size, (len(edited), size)
assert FDT(edited).reserved_memory() == tree.reserved_memory()
padded = bytearray(edited.ljust(size, b'\0'))
struct.pack_into('>I', padded, 4, size)
candidate = bytearray(raw)
candidate[offset+off:offset+off+size] = padded
assert candidate[:offset+off] == raw[:offset+off]
assert candidate[offset+off+size:] == raw[offset+off+size:]
(out / 'vendor_boot_a-wifi.img').write_bytes(candidate)
subprocess.run(['dtc', '-I', 'dtb', '-O', 'dts', '-o', str(out / 'wifi-added.dts'), str(path)],
               check=True, stderr=(out / 'dtc-warnings.txt').open('w'))
report = dict(source_sha256=sha(raw), candidate_sha256=sha(candidate), bytes=len(candidate),
              changed_existing_nodes=changed, added_nodes=sorted(set(after)-set(nodes)),
              other_container_bytes_unchanged=True, phone_written=False,
              reference='research/aston/sm8550-oneplus-aston.dts; factory PJA110 CNSS/PCIe wiring')
(out / 'vendor-manifest.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report, indent=2))
