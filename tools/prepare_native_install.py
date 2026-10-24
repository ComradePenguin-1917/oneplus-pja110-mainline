"""Read-only device inventory and verified backups for native installation."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'out/native-install-20261016'
KEYS = ROOT / 'out/usb-ncm-20261013/ssh'
SSH = ['C:/Windows/System32/OpenSSH/ssh.exe', '-F', 'none', '-T',
       '-i', str(KEYS/'client_key_host'), '-o', 'BatchMode=yes',
       '-o', 'IdentitiesOnly=yes', '-o', 'StrictHostKeyChecking=yes',
       '-o', f'UserKnownHostsFile={KEYS/"known_hosts"}',
       '-o', 'ConnectTimeout=8', '-o', 'ServerAliveInterval=5',
       'root@169.254.42.1']
PARTS = ['boot_a', 'init_boot_a', 'vendor_boot_a', 'dtbo_a',
         'boot_b', 'init_boot_b', 'vendor_boot_b', 'dtbo_b',
         'vbmeta_a', 'vbmeta_b', 'misc', 'persist', 'modemst1', 'modemst2',
         'fsg', 'fsc', 'ocdt', 'cdt', 'devinfo', 'apdp']


def read(cmd):
    p = subprocess.run(SSH+[cmd], capture_output=True, timeout=180)
    p.check_returncode()
    return p.stdout


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda: f.read(4*1024*1024), b''):
            h.update(b)
    return h.hexdigest()


def inventory():
    data = read('''set -e
uname -a
cat /proc/sys/kernel/random/boot_id
cat /proc/cmdline
cat /proc/mounts
for f in /sys/class/block/sd*/uevent; do
 echo BLOCK_BEGIN
 cat "$f"
 d=${f%/uevent}
 echo SECTORS=$(cat "$d/size")
done
''')
    (OUT/'inventory.txt').write_bytes(data)
    partitions = {}
    for record in data.decode().split('BLOCK_BEGIN')[1:]:
        props = dict(line.split('=', 1) for line in record.splitlines() if '=' in line)
        if 'PARTNAME' in props:
            name, dev = props['PARTNAME'], props['DEVNAME']
            if name not in PARTS+['userdata', 'super', 'metadata']:
                continue
            assert name not in partitions
            assert dev.startswith('sd') and dev.isalnum()
            partitions[name] = {'device': dev, 'bytes': int(props['SECTORS'])*512}
    assert all(name in partitions for name in PARTS), set(PARTS)-partitions.keys()
    (OUT/'partitions.json').write_text(json.dumps(partitions, indent=2)+'\n')
    print('Inventory captured; userdata bytes:', partitions['userdata']['bytes'])
    return partitions


def backup():
    parts = inventory()
    dest = OUT/'backup'
    dest.mkdir(exist_ok=True)
    required = sum(parts[n]['bytes'] for n in PARTS)
    assert shutil.disk_usage(OUT).free > required+512*1024*1024
    results = {}
    for name in PARTS:
        info = parts[name]
        dev = info['device']
        check = f'test "$(cat /sys/class/block/{dev}/uevent | sed -n \'s/^PARTNAME=//p\')" = {name}'
        remote = read(f'{check} && sha256sum /dev/{dev}').decode().split()[0]
        path = dest/(name+'.img')
        if not (path.exists() and path.stat().st_size == info['bytes'] and digest(path) == remote):
            partial = path.with_suffix('.partial')
            with partial.open('wb') as f:
                p = subprocess.run(SSH+[f'{check} && cat /dev/{dev}'], stdout=f,
                                   stderr=subprocess.PIPE, timeout=300)
            p.check_returncode()
            assert partial.stat().st_size == info['bytes'], name
            assert digest(partial) == remote, name
            partial.replace(path)
        results[name] = {**info, 'sha256': remote, 'verified': True}
        (OUT/'backup-verification.json').write_text(json.dumps(results, indent=2)+'\n')
        print(name, 'size and SHA256 verified', flush=True)
    print('PASS: read-only off-device backup complete; no phone writes')


def rescue_check():
    state = read('uname -a; cat /proc/sys/kernel/random/boot_id; cat /proc/1/comm; cat /proc/cmdline; cat /proc/mounts; cat /tmp/touch-init.log')
    assert b'#24 SMP' in state and b'\ninit\n' in state
    assert b'report rate code=3' in read('dmesg | grep "PJA_ASTON fixed report rate"')
    table = json.loads((ROOT/'out/boot-success-20261014/native-install-before/gpt.json').read_text())
    entries = {e['name']: e for disk in table for c in disk['copies'] if c['side']=='primary' for e in c.get('entries', [])}
    assert entries['boot_b']['active'] and entries['boot_b']['successful']
    current = inventory()
    saved = json.loads((OUT/'backup-verification.json').read_text())
    for n in ['boot_b', 'init_boot_b', 'vendor_boot_b', 'dtbo_b']:
        assert read(f"sha256sum /dev/{current[n]['device']}").decode().split()[0] == saved[n]['sha256']
    mounts = read('cat /proc/mounts').decode()
    for n in ['userdata', 'super']:
        assert '/dev/'+current[n]['device']+' ' not in mounts
    (OUT/'rescue-check.txt').write_bytes(state)
    print('PASS: current slot B is verified #24 standalone rescue; userdata/super not mounted')


def rescue_reboot():
    rescue_check()
    # The RAM systemd guest must be shut down through its existing helper first.
    assert read('test ! -f /tmp/pmos-systemd-nspawn.pid && echo READY').strip() == b'READY'
    before = read('cat /proc/sys/kernel/random/boot_id').strip()
    (OUT/'rescue-before-boot-id.txt').write_bytes(before+b'\n')
    try:
        read('sync; reboot -f')
    except (subprocess.SubprocessError, OSError):
        pass  # SSH may disconnect during the requested reboot; prove recovery below.
    deadline = time.monotonic()+100
    while time.monotonic()<deadline:
        time.sleep(3)
        try:
            after = read('cat /proc/sys/kernel/random/boot_id; uname -a; cat /proc/1/comm; cat /proc/mounts')
        except (subprocess.SubprocessError, OSError):
            continue
        if after.splitlines()[0] == before:
            continue
        assert b'#24 SMP' in after and b'\ninit\n' in after
        assert b'/dev/loop' not in after
        (OUT/'rescue-after-reboot.txt').write_bytes(after)
        (OUT/'rescue-result.json').write_text(json.dumps({
            'slot': 'b', 'kernel': '#24', 'new_boot_id': after.splitlines()[0].decode(),
            'automatic_rescue_ssh': True, 'ram_root_only': True,
            'phone_images_reflashed': False}, indent=2)+'\n')
        print('PASS: fresh rescue boot and automatic authenticated SSH; no persistent root mounted')
        return
    raise RuntimeError('Rescue reboot not confirmed within observation window')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=['inventory', 'backup', 'rescue-check', 'rescue-reboot'])
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    {'inventory': inventory, 'backup': backup, 'rescue-check': rescue_check,
     'rescue-reboot': rescue_reboot}[args.stage]()
