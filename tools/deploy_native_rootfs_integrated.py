"""Stage and install the reviewed userdata image from the running B rescue.

flash is destructive to Android userdata. Never writes an outer disk, GPT,
firmware, slot images, or a selected slot. Rootfs growth is deferred.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import time

from prepare_native_install import SSH, read, inventory, digest

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'out/native-install-20261017'
SOURCE=BASE/'rootfs-integrated'
OUT=BASE/'charger-rootfs-deployment'
REMOTE='/tmp/native-userdata'


def run(cmd, source=None, timeout=300):
    if source:
        with source.open('rb') as f:
            p=subprocess.run(SSH+[cmd],stdin=f,capture_output=True,timeout=timeout)
    else:
        p=subprocess.run(SSH+[cmd],capture_output=True,timeout=timeout)
    with (OUT/'operations.log').open('ab') as f:
        f.write((cmd+'\n').encode()+p.stdout+p.stderr)
    p.check_returncode()
    return p.stdout


def manifest():
    m=json.loads((SOURCE/'manifest.json').read_text())
    assert digest(SOURCE/'userdata-prefix.img.gz')==m['compressed_sha256']
    assert digest(SOURCE/'userdata-backup-gpt.bin')==m['tail_sha256']
    assert m['tail_offset']+m['tail_bytes']==m['userdata_bytes']
    return m


def stage():
    m=manifest()
    assert b'#24 SMP' in read('uname -a')
    free=int(read('df -Pk /tmp').decode().splitlines()[-1].split()[3])*1024
    assert free>m['prefix_bytes']+m['compressed_bytes']+256*1024**2
    run(f'mkdir -p {REMOTE}')
    value=run(f'cat > {REMOTE}/prefix.gz && sha256sum {REMOTE}/prefix.gz',SOURCE/'userdata-prefix.img.gz').decode().split()[0]
    assert value==m['compressed_sha256']
    run(f'gzip -dc {REMOTE}/prefix.gz > {REMOTE}/prefix.img')
    assert run(f'sha256sum {REMOTE}/prefix.img').decode().split()[0]==m['prefix_sha256']
    assert run(f'wc -c < {REMOTE}/prefix.img').strip()==str(m['prefix_bytes']).encode()
    assert run(f'cat > {REMOTE}/tail.bin && sha256sum {REMOTE}/tail.bin',SOURCE/'userdata-backup-gpt.bin').decode().split()[0]==m['tail_sha256']
    result={'staged_in_phone_ram':True,'boot_id':read('cat /proc/sys/kernel/random/boot_id').strip().decode(),
            'prefix_sha256':m['prefix_sha256'],'tail_sha256':m['tail_sha256'],
            'phone_partitions_written':False}
    (OUT/'staged.json').write_text(json.dumps(result,indent=2)+'\n')
    print('PASS: image staged and decompressed in RAM; all hashes match, no partition writes')


def flash():
    m=manifest()
    verified=json.loads((ROOT/'out/postmarketos-integration-20261016/image-verification.json').read_text())
    assert m['root_uuid']==verified['image']['root_uuid']
    staged=json.loads((OUT/'staged.json').read_text())
    assert read('cat /proc/sys/kernel/random/boot_id').strip().decode()==staged['boot_id']
    assert not (OUT/'write-started.json').exists(), 'Inspect prior attempt before rerun'
    parts=inventory()
    assert parts['userdata']['bytes']==m['userdata_bytes']
    assert parts['userdata']['device'] not in {parts[n]['device'] for n in ['super','persist','boot_a','boot_b']}
    dev=parts['userdata']['device']
    assert dev.startswith('sd') and dev.isalnum()
    mounts=read('cat /proc/mounts').decode()
    assert '/dev/loop' not in mounts
    assert '/dev/'+dev+' ' not in mounts
    assert run(f'sha256sum {REMOTE}/prefix.img').decode().split()[0]==m['prefix_sha256']
    assert run(f'sha256sum {REMOTE}/tail.bin').decode().split()[0]==m['tail_sha256']
    startup=json.loads((ROOT/'out/native-install-20261016/native-images/manifest.json').read_text())
    backup=json.loads((ROOT/'out/native-install-20261016/backup-verification.json').read_text())
    for name in ['boot_b','init_boot_b','vendor_boot_b','dtbo_b']:
        expected=backup[name]['sha256']
        assert run(f"test \"$(sed -n 's/^PARTNAME=//p' /sys/class/block/{parts[name]['device']}/uevent)\" = {name} && sha256sum /dev/{parts[name]['device']}").decode().split()[0]==expected
    tag='native-rootfs-before-'+str(time.time_ns())
    subprocess.run(['python',str(ROOT/'tools/inspect_boot_gpt.py'),tag],check=True,timeout=90,capture_output=True)
    gpt_path=ROOT/'out/boot-success-20261014'/tag/'gpt.json'
    gpt=json.loads(gpt_path.read_text())
    for d in gpt:
        if d['device']=='sde': continue
        a,b=d['copies']
        assert a['header_crc_valid'] and b['header_crc_valid'] and a['table_crc_valid'], (d['device'], a, b)
        assert a['entries']==b['entries']
    entries={e['name']:e for d in gpt for c in d['copies'] if c['side']=='primary' for e in c['entries']}
    assert entries['boot_b']['active'] and not entries['boot_a']['active']
    # Keep limited pre-write geometry evidence; this is NOT a user-data backup.
    (OUT/'userdata-first-64k-before.bin').write_bytes(read(f'dd if=/dev/{dev} bs=4096 count=16 2>/dev/null'))
    (OUT/'userdata-last-64k-before.bin').write_bytes(read(f"dd if=/dev/{dev} bs=4096 skip={m['userdata_bytes']//4096-16} count=16 2>/dev/null"))
    result={'target_partition':'userdata','device':dev,'bytes':m['userdata_bytes'],
            'before_gpt':str(gpt_path.relative_to(ROOT)), 'boot_id':staged['boot_id'],
            'overwrites_android_user_data':True,'slot_changed':False,'reboot_requested':False}
    (OUT/'write-started.json').write_text(json.dumps(result,indent=2)+'\n')
    guard=f'test "$(sed -n \'s/^PARTNAME=//p\' /sys/class/block/{dev}/uevent)" = userdata && test "$(cat /sys/class/block/{dev}/size)" = {m["userdata_bytes"]//512}'
    run(guard+f' && dd if={REMOTE}/prefix.img of=/dev/{dev} bs=1048576 conv=fsync && sync')
    assert m['tail_offset']%4096==0
    run(guard+f' && dd if={REMOTE}/tail.bin of=/dev/{dev} bs=4096 seek={m["tail_offset"]//4096} conv=notrunc,fsync && sync')
    assert run(f'head -c {m["prefix_bytes"]} /dev/{dev} | sha256sum').decode().split()[0]==m['prefix_sha256']
    assert run(f'dd if=/dev/{dev} bs=4096 skip={m["tail_offset"]//4096} count={m["tail_bytes"]//4096} 2>/dev/null | sha256sum').decode().split()[0]==m['tail_sha256']
    result.update({'prefix_readback_verified':True,'backup_gpt_readback_verified':True,
                   'rootfs_capacity_expanded':False,'native_phone_boot_verified':False})
    (OUT/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    m['phone_partitions_written']=True
    m['userdata_readback_verified']=True
    (SOURCE/'manifest.json').write_text(json.dumps(m,indent=2)+'\n')
    print('PASS: userdata prefix and end-of-partition backup GPT written and readback verified; still on B rescue')


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('step',choices=['stage','flash'])
    args=ap.parse_args()
    OUT.mkdir(parents=True,exist_ok=True)
    {'stage':stage,'flash':flash}[args.step]()
