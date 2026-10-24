"""Guarded slot-A-only image deployment from the verified slot-B RAM rescue.

Never writes userdata, B-slot images or GPT; does not reboot or select a slot.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import time

from prepare_native_install import SSH, read, inventory, digest

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT/'out/native-install-20261016'
IMAGES = BASE/'native-images'
OUT = BASE/'deployment'
TARGETS = ['dtbo_a', 'vendor_boot_a', 'init_boot_a', 'boot_a']
RESCUE = ['boot_b', 'init_boot_b', 'vendor_boot_b', 'dtbo_b']


def command(cmd, data=None, timeout=300):
    p=subprocess.run(SSH+[cmd], input=data, capture_output=True, timeout=timeout)
    with (OUT/'ssh-operations.log').open('ab') as f:
        f.write((cmd+'\n').encode()+p.stdout+p.stderr)
    p.check_returncode()
    return p.stdout


def label_guard(name, parts):
    dev=parts[name]['device']
    assert dev.startswith('sd') and dev.isalnum()
    return (f'test "$(sed -n \'s/^PARTNAME=//p\' /sys/class/block/{dev}/uevent)" = {name}'
            f' && test "$(cat /sys/class/block/{dev}/size)" = {parts[name]["bytes"]//512}')


def validate_images():
    m=json.loads((IMAGES/'manifest.json').read_text())
    assert m['target_slot']=='a' and m['rescue_slot']=='b'
    assert m['qemu_combined_payload_tested'] and m['local_pack_unpack_checks_passed']
    for name in TARGETS:
        p=IMAGES/(name+'.img')
        assert p.stat().st_size==m['files'][p.name]['bytes']
        assert digest(p)==m['files'][p.name]['sha256'], name
    return m


def fresh_state():
    tag='native-a-flash-'+str(time.time_ns())
    p=subprocess.run(['python', str(ROOT/'tools/inspect_boot_gpt.py'), tag],
                     capture_output=True, timeout=90)
    (OUT/(tag+'.log')).write_bytes(p.stdout+p.stderr)
    p.check_returncode()
    gpt_path=ROOT/'out/boot-success-20261014'/tag/'gpt.json'
    gpt=json.loads(gpt_path.read_text())
    all_entries={}
    for disk in gpt:
        a,b=disk['copies']
        assert all(c['header_crc_valid'] and c['table_crc_valid'] for c in [a,b])
        assert a['entries']==b['entries']
        for e in a['entries']:
            if e['name'] in TARGETS+RESCUE:
                assert e['name'] not in all_entries
                all_entries[e['name']]=e
    assert all_entries['boot_b']['active'] and all_entries['boot_b']['successful']
    assert not all_entries['boot_a']['active']
    parts=inventory()
    state=read('uname -a; cat /proc/sys/kernel/random/boot_id; cat /proc/1/comm; cat /proc/mounts')
    assert b'#24 SMP' in state and b'\ninit\n' in state
    mounts=read('cat /proc/mounts').decode()
    for name in TARGETS+['userdata','super']:
        assert '/dev/'+parts[name]['device']+' ' not in mounts
    saved=json.loads((BASE/'backup-verification.json').read_text())
    hashes={}
    for name in TARGETS+RESCUE:
        hashes[name]=command(label_guard(name,parts)+f" && sha256sum /dev/{parts[name]['device']}").decode().split()[0]
        assert hashes[name]==saved[name]['sha256'], name
    return {'gpt_path':str(gpt_path.relative_to(ROOT)), 'partitions':parts,
            'boot_id':state.splitlines()[1].decode(), 'before_hashes':hashes}


def preflight():
    m=validate_images()
    s=fresh_state()
    for n in TARGETS:
        assert s['partitions'][n]['bytes']==m['files'][n+'.img']['bytes']
    (OUT/'preflight.json').write_text(json.dumps(s,indent=2)+'\n')
    print('PASS: source images, inactive A, active successful B, labels and sizes verified')
    return m,s


def flash():
    m,s=preflight()
    assert not (OUT/'write-started.json').exists(), 'Preserve prior deployment evidence; inspect before retry'
    command('mkdir -p /tmp/native-slot-a')
    result={'target_slot':'a','rescue_slot':'b','writes':{}, 'reboot_requested':False,
            'userdata_written':False, 'slot_selection_changed':False}
    (OUT/'write-started.json').write_text(json.dumps(s,indent=2)+'\n')
    for name in TARGETS:
        info=m['files'][name+'.img']
        dev=s['partitions'][name]['device']
        remote=f'/tmp/native-slot-a/{name}.img'
        sent=command(f'cat > {remote} && sha256sum {remote}',
                     (IMAGES/(name+'.img')).read_bytes()).decode().split()[0]
        assert sent==info['sha256']
        assert read('cat /proc/sys/kernel/random/boot_id').strip().decode()==s['boot_id']
        # An explicit per-target label/size check immediately precedes every dd.
        command(label_guard(name,s['partitions'])+
                f' && dd if={remote} of=/dev/{dev} bs=1048576 conv=fsync && sync')
        actual=command(label_guard(name,s['partitions'])+f' && sha256sum /dev/{dev}').decode().split()[0]
        assert actual==info['sha256'], name
        result['writes'][name]={'device':dev, **info, 'readback_verified':True}
        (OUT/'result.json').write_text(json.dumps(result,indent=2)+'\n')
        command(f'rm {remote}')
        print(name, 'written and full-partition SHA256 readback verified',flush=True)
    for name in RESCUE:
        actual=command(label_guard(name,s['partitions'])+
                       f" && sha256sum /dev/{s['partitions'][name]['device']}").decode().split()[0]
        assert actual==s['before_hashes'][name],name
    result['all_four_a_partitions_verified']=True
    result['all_four_b_partitions_unchanged']=True
    result['native_phone_boot_verified']=False
    (OUT/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    m['phone_partitions_written']=True
    m['a_startup_partitions_readback_verified']=True
    (IMAGES/'manifest.json').write_text(json.dumps(m,indent=2)+'\n')
    print('PASS: four A startup partitions flashed; B unchanged; no reboot or userdata write')


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('stage', choices=['preflight','flash'])
    args=ap.parse_args()
    OUT.mkdir(parents=True,exist_ok=True)
    {'preflight':preflight,'flash':flash}[args.stage]()
