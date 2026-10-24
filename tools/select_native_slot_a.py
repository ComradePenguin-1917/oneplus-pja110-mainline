"""Select installed A using upstream qbootctl and its UFS BSG support."""
import hashlib
import json
import re
import subprocess
from prepare_native_install import read, SSH, ROOT, OUT
from boot_native_pmos import preconditions

preconditions()
dest = OUT/'first-native-boot'
dest.mkdir(exist_ok=True)
assert not (dest/'qbootctl-select-started.txt').exists(), 'Inspect previous selection before retrying'
state = read('uname -a; cat /proc/mounts; cat /sys/bus/platform/devices/1d84000.ufshc/attributes/boot_lun_enabled; test -c /dev/bsg/ufs-bsg0')
assert b'#24 SMP' in state and b'/dev/loop' not in state
raw = read('for f in /sys/class/block/sd*/uevent; do cat "$f"; echo END; done').decode()
parts = {}
for record in raw.split('END'):
    props = dict(x.split('=', 1) for x in record.splitlines() if '=' in x)
    if 'PARTNAME' in props:
        name, dev = props['PARTNAME'], props['DEVNAME']
        assert re.fullmatch(r'[a-zA-Z0-9_-]+', name) and re.fullmatch(r'sd[a-z]+[0-9]+', dev)
        parts.setdefault(name, []).append(dev)
read('mkdir -p /dev/disk/by-partlabel')
for name, devices in parts.items():
    if len(devices) != 1:
        assert not name.endswith(('_a', '_b'))
        continue
    read(f'ln -sfn /dev/{devices[0]} /dev/disk/by-partlabel/{name}')
expected = json.loads((OUT/'deployment/result.json').read_text())['writes']
backup = json.loads((OUT/'backup-verification.json').read_text())
for name in ('boot', 'init_boot', 'vendor_boot', 'dtbo'):
    for slot in ('a', 'b'):
        label = name+'_'+slot
        value = read(f'sha256sum /dev/{parts[label][0]}').decode().split()[0]
        assert value == (expected if slot == 'a' else backup)[label]['sha256'], label
binary = (ROOT/'out/boot-success-20261014/qbootctl-aarch64').read_bytes()
p = subprocess.run(SSH+['cat > /tmp/native-qbootctl; chmod 700 /tmp/native-qbootctl; sha256sum /tmp/native-qbootctl'], input=binary, capture_output=True, timeout=30)
p.check_returncode()
assert p.stdout.decode().split()[0] == hashlib.sha256(binary).hexdigest()
before = read('/tmp/native-qbootctl -a; /tmp/native-qbootctl -n 1')
assert b'Active slot: _b' in before and b'is marked successful' in before
(dest/'qbootctl-before.txt').write_bytes(before)
(dest/'qbootctl-select-started.txt').write_text('Selecting A using upstream qbootctl, without ignore-missing-bsg\n')
selected = read('set -e; /tmp/native-qbootctl -s 0; sync; /tmp/native-qbootctl -a; /tmp/native-qbootctl -n 1; cat /sys/bus/platform/devices/1d84000.ufshc/attributes/boot_lun_enabled')
(dest/'qbootctl-selected.txt').write_bytes(selected)
assert b'Active slot: _a' in selected and b'is marked successful' in selected
print(selected.decode())
print('A selected; B remains marked successful; not rebooted yet')
