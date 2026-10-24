"""Activate the installed slot-A native candidate through the stock fastboot UI."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import time

from prepare_native_install import SSH, read

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'out/native-install-20261016'
OUT=BASE/'first-native-boot'
FB=['C:/platform-tools/fastboot.exe','-s','SERIAL']


def fb(args,timeout=15):
    p=subprocess.run(FB+args,capture_output=True,timeout=timeout)
    with (OUT/'fastboot.log').open('ab') as f:
        f.write(('COMMAND '+' '.join(args)+'\n').encode()+p.stdout+p.stderr)
    p.check_returncode()
    return (p.stdout+p.stderr).decode(errors='replace')


def preconditions():
    result=json.loads((BASE/'rootfs-deployment/result.json').read_text())
    assert result['prefix_readback_verified'] and result['backup_gpt_readback_verified']
    assert result.get('readonly_mount_verified'), 'Mount/readback inspection must complete first'


def bootloader():
    preconditions()
    state=read('uname -a; cat /proc/sys/kernel/random/boot_id; cat /proc/mounts')
    assert b'#24 SMP' in state and b'/dev/loop' not in state
    (OUT/'before-bootloader.txt').write_bytes(state)
    helper=(ROOT/'out/init-experiment-20261012/native-init').read_bytes()
    assert helper[:4]==b'\x7fELF' and helper[18:20]==b'\xb7\x00'
    p=subprocess.run(SSH+['cat > /tmp/native-reboot-bootloader; chmod 700 /tmp/native-reboot-bootloader; sha256sum /tmp/native-reboot-bootloader'],input=helper,capture_output=True,timeout=30)
    p.check_returncode()
    assert p.stdout.decode().split()[0]==hashlib.sha256(helper).hexdigest()
    try:
        p=subprocess.run(SSH+['sync; /tmp/native-reboot-bootloader'],capture_output=True,timeout=15)
        (OUT/'bootloader-request.txt').write_bytes(p.stdout+p.stderr)
    except subprocess.TimeoutExpired:
        (OUT/'bootloader-request.txt').write_text('Expected SSH disconnect/timeout; verify fastboot separately\n')
    for _ in range(15):
        p=subprocess.run(['C:/platform-tools/fastboot.exe','devices'],capture_output=True,timeout=5)
        if b'SERIAL' in p.stdout:
            print('Fastboot detected; A not yet activated',flush=True)
            return
        time.sleep(2)
    raise RuntimeError('Fastboot not detected; A not activated by this helper')


def activate():
    preconditions()
    assert 'unlocked: yes' in fb(['getvar','unlocked'])
    assert 'current-slot: b' in fb(['getvar','current-slot'])
    assert 'slot-successful:b: yes' in fb(['getvar','slot-successful:b'])
    print(fb(['set_active','a']),flush=True)
    assert 'current-slot: a' in fb(['getvar','current-slot'])
    (OUT/'a-activated.json').write_text(json.dumps({'slot':'a','time':time.time(),
        'rootfs_readback_verified':True,'native_boot_verified':False},indent=2)+'\n')
    print(fb(['reboot']),flush=True)
    (OUT/'reboot-requested.txt').write_text(time.strftime('%Y-%m-%dT%H:%M:%S')+'\n')


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('step',choices=['bootloader','activate'])
    args=ap.parse_args()
    OUT.mkdir(parents=True,exist_ok=True)
    {'bootloader':bootloader,'activate':activate}[args.step]()
