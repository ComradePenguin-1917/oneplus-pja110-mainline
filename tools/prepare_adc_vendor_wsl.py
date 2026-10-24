"""Add only ADC nodes to the verified vendor boot container; no phone writes."""
from pathlib import Path
import hashlib
import json
import struct
import subprocess
import sys
win = Path('/mnt/h/workspace/PJA110-Mainline')
sys.path.insert(0, str(win / 'tools'))
from fdt import FDT, scan_for_fdt
out = win / 'out/native-install-20261017/adc-gen3'
src = win / 'out/native-install-20261017/charger-startup/vendor_boot_a.img'
raw = src.read_bytes()
sha = lambda b: hashlib.sha256(b).hexdigest()
assert sha(raw) == '9f51fb62621d74f333d4bda52c436bc0860d203940bfbdc96db5c409d316f700'
align = lambda n: (n + 4095) // 4096 * 4096
rdsize = struct.unpack_from('<I', raw, 24)[0]
hsize, dsize = struct.unpack_from('<II', raw, 2096)
offset = align(align(hsize) + rdsize)
entries = [(off, size, tree) for off, size, tree in scan_for_fdt(raw[offset:offset+dsize]) if tree.nodes().get('/', {}).get('model') == b'OnePlus Ace 2 Pro\0']
assert len(entries) == 1
off, size, tree = entries[0]
nodes = tree.nodes()
pmk = '/soc@0/spmi@c400000/pmic@0'
gpio = '/soc@0/spmi@c400000/pmic@7/gpio@8800'
spmi = '/soc@0/spmi@c400000'
assert pmk in nodes and gpio in nodes and spmi in nodes
adc = pmk + '/adc@9000'
pin = gpio + '/subboard-ntc-state'
assert adc not in nodes and pin not in nodes
phandle = max(struct.unpack('>I', n['phandle'])[0] for n in nodes.values() if 'phandle' in n) + 1
irq_parent = struct.unpack('>I', nodes[spmi]['phandle'])[0]
path = out / 'adc-added.dtb'
path.write_bytes(raw[offset+off:offset+off+size])
def create(node):
    subprocess.run(['fdtput', '-c', str(path), node], check=True)
def prop(node, name, values=None, kind='x'):
    args = ['fdtput', '-t', kind, str(path), node, name]
    if values is not None:
        args += [str(v) if kind == 's' else format(v, 'x') for v in values]
    subprocess.run(args, check=True)
create(pin)
prop(pin, 'phandle', [phandle])
prop(pin, 'pins', ['gpio6'], 's')
prop(pin, 'function', ['normal'], 's')
prop(pin, 'bias-high-impedance')
create(adc)
prop(adc, 'compatible', ['qcom,spmi-adc5-gen3'], 's')
prop(adc, 'reg', [0x9000, 0x9100])
prop(adc, 'interrupts-extended', [irq_parent, 0, 0x90, 1, 1, irq_parent, 0, 0x91, 1, 1])
prop(adc, '#address-cells', [1])
prop(adc, '#size-cells', [0])
prop(adc, '#io-channel-cells', [1])
prop(adc, 'pinctrl-names', ['default'], 's')
prop(adc, 'pinctrl-0', [phandle])
channel = adc + '/channel@74c'
create(channel)
prop(channel, 'reg', [0x74c])
prop(channel, 'label', ['subboard_temp'], 's')
prop(channel, 'qcom,pre-scaling', [1, 1])
prop(channel, 'qcom,ratiometric')
prop(channel, 'qcom,hw-settle-time', [200])
edited = path.read_bytes()
after = FDT(edited).nodes()
assert all(after.get(p) == props for p, props in nodes.items())
assert set(after) - set(nodes) == {pin, adc, channel}
assert FDT(edited).reserved_memory() == tree.reserved_memory()
assert len(edited) <= size
padded = bytearray(edited.ljust(size, b'\0'))
struct.pack_into('>I', padded, 4, size)
candidate = bytearray(raw)
candidate[offset+off:offset+off+size] = padded
assert candidate[:offset+off] == raw[:offset+off]
assert candidate[offset+off+size:] == raw[offset+off+size:]
(out / 'vendor_boot_a-adc.img').write_bytes(candidate)
report = dict(source_sha256=sha(raw), candidate_sha256=sha(candidate), bytes=len(candidate), added_nodes=sorted(set(after)-set(nodes)), existing_properties_unchanged=True, other_container_bytes_unchanged=True, phone_written=False)
(out / 'vendor-manifest.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report, indent=2))
