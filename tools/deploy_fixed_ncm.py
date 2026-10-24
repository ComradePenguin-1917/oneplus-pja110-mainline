"""B-only debug boot deployment with before/after partition and SSH evidence."""
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'out/debug-ncm-fixed-20261013'
BASE=ROOT/'out/user-init-usb-serial-diag-20261013'
SSH=ROOT/'out/usb-ncm-20261013/ssh'
FB=['C:/platform-tools/fastboot.exe','-s','SERIAL']
COMMAND=['C:/Windows/System32/OpenSSH/ssh.exe','-F','none','-T','-i',str(SSH/'client_key_host'),
         '-o','BatchMode=yes','-o','IdentitiesOnly=yes','-o','StrictHostKeyChecking=yes',
         '-o',f'UserKnownHostsFile={SSH/"known_hosts"}','-o','ConnectTimeout=5',
         '-o','ServerAliveInterval=5','root@169.254.42.1']
PARTS={'boot_a':'sde13','vendor_boot_a':'sde24','init_boot_a':'sde32','dtbo_a':'sde17',
       'boot_b':'sde45','vendor_boot_b':'sde56','init_boot_b':'sde63','dtbo_b':'sde49'}

def ssh(command,data=None,timeout=90):
    result=subprocess.run(COMMAND+[command],input=data,capture_output=True,timeout=timeout)
    if result.returncode:
        (OUT/'last-ssh-error.txt').write_bytes(result.stderr)
        raise RuntimeError(result.stderr.decode(errors='replace'))
    return result.stdout

def hashes():
    result={}
    for name,dev in PARTS.items():
        # Validate the label before using a block device path.
        label=ssh(f"grep '^PARTNAME=' /sys/class/block/{dev}/uevent").decode().strip()
        assert label=='PARTNAME='+name, label
        result[name]=ssh(f'sha256sum /dev/{dev}').decode().split()[0]
    return result

def fb(args):
    p=subprocess.run(FB+args,capture_output=True,timeout=90)
    with (OUT/'fastboot.log').open('ab') as f:
        f.write(('COMMAND '+' '.join(args)+'\n').encode()+p.stdout+p.stderr)
    p.check_returncode()
    print((p.stdout+p.stderr).decode(errors='replace'),flush=True)
    return p.stdout+p.stderr

mode=sys.argv[1]
if mode=='preflight':
    assert not (OUT/'device-before.json').exists(), 'preserve evidence'
    before=hashes()
    original={n:hashlib.sha256((ROOT/'backup'/f'{n}.img').read_bytes()).hexdigest() for n in PARTS if n.endswith('_a')}
    assert all(before[n]==h for n,h in original.items()), 'A baseline mismatch'
    for part,file in [('vendor_boot_b','vendor_boot_b-xigua-r1.img'),('init_boot_b','init_boot_b-xigua-r1.img'),('dtbo_b','dtbo_b-avb-noop.img')]:
        assert before[part]==hashlib.sha256((BASE/file).read_bytes()).hexdigest(),part
    old=(BASE/'boot-xigua-r1.img').read_bytes()
    prefix=ssh(f'head -c {len(old)} /dev/sde45 | sha256sum').decode().split()[0]
    assert prefix==hashlib.sha256(old).hexdigest(), 'old boot differs from proven #8'
    (OUT/'device-before.json').write_text(json.dumps(before,indent=2)+'\n')
    (OUT/'device-before.txt').write_bytes(ssh('uname -a; cat /proc/cmdline; ip addr show usb0; cat /proc/uptime'))
    display=ROOT/'out/display-baseline-20261013'
    (display/'mainline-live.dtb').write_bytes(ssh('cat /sys/firmware/fdt'))
    (display/'mainline-state.txt').write_bytes(ssh('ls -l /sys/class/drm; cat /sys/kernel/debug/devices_deferred 2>/dev/null; dmesg'))
    print('PASS: all A hashes and retained B ancillary images verified; #8 boot prefix matched')
elif mode=='bootloader':
    assert (OUT/'device-before.json').exists()
    helper=(ROOT/'out/init-experiment-20261012/native-init').read_bytes()
    assert helper[:4]==b'\x7fELF'
    ssh('cat > /tmp/reboot-bootloader; chmod 700 /tmp/reboot-bootloader',helper)
    p=subprocess.run(COMMAND+['/tmp/reboot-bootloader'],capture_output=True,timeout=15)
    (OUT/'bootloader-request.txt').write_bytes(p.stdout+p.stderr)
    print('Requested bootloader; disconnect expected, fastboot must be verified separately')
elif mode=='flash':
    assert (OUT/'device-before.json').exists()
    manifest=json.loads((OUT/'manifest.json').read_text())
    image=OUT/'boot-xigua-r1.img'
    assert hashlib.sha256(image.read_bytes()).hexdigest()==manifest['files'][image.name]['sha256']
    init_image=OUT/'init_boot_b-xigua-r1.img'
    assert hashlib.sha256(init_image.read_bytes()).hexdigest()==manifest['files'][init_image.name]['sha256']
    assert b'QEMU debug userspace validated' in (OUT/'qemu-console.txt').read_bytes()
    assert 'current-slot: b' in fb(['getvar','current-slot']).decode(errors='replace')
    assert 'unlocked: yes' in fb(['getvar','unlocked']).decode(errors='replace')
    assert 'slot-successful:a: yes' in fb(['getvar','slot-successful:a']).decode(errors='replace')
    fb(['flash','boot_b',str(image)])
    fb(['flash','init_boot_b',str(init_image)])
    fb(['set_active','b'])
    fb(['reboot'])
    (OUT/'flashed-at.txt').write_text(time.strftime('%Y-%m-%dT%H:%M:%S%z'))
elif mode=='verify':
    assert (OUT/'flashed-at.txt').exists()
    identity=ssh('uname -a; id; /sbin/dropbearmulti dropbear -V 2>&1; cat /proc/uptime; cat /tmp/debug-ssh.pid; cat /tmp/debug-ssh.log; ip addr show usb0; cat /sys/class/udc/*/state')
    assert b'uid=0' in identity and b'Dropbear v2026.94' in identity and b'169.254.42.1' in identity
    (OUT/'device-after.txt').write_bytes(identity)
    assert ssh('cat /init')==(OUT/'init.sh').read_bytes()
    after=hashes()
    before=json.loads((OUT/'device-before.json').read_text())
    assert all(after[n]==before[n] for n in PARTS if n not in ('boot_b','init_boot_b')), 'unexpected partition change'
    assert after['init_boot_b']==hashlib.sha256((OUT/'init_boot_b-xigua-r1.img').read_bytes()).hexdigest()
    image=(OUT/'boot-xigua-r1.img').read_bytes()
    digest=hashlib.sha256(image).hexdigest()
    assert ssh(f'head -c {len(image)} /dev/sde45 | sha256sum').decode().split()[0]==digest
    (OUT/'device-after.json').write_text(json.dumps(after,indent=2)+'\n')
    (OUT/'mainline-dmesg.txt').write_bytes(ssh('dmesg'))
    data=bytes(range(256))*4096
    remote=ssh('cat > /tmp/fixed-debug-check.bin; sha256sum /tmp/fixed-debug-check.bin',data).decode().split()[0]
    assert remote==hashlib.sha256(data).hexdigest() and ssh('cat /tmp/fixed-debug-check.bin')==data
    manifest=json.loads((OUT/'manifest.json').read_text()); manifest['phone_execution_confirmed']=True
    (OUT/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    (OUT/'result.json').write_text(json.dumps({'automatic_ssh_verified':True,'existing_host_identity_verified':True,
        'boot_readback_prefix_verified':True,'other_six_partitions_unchanged':True,
        'binary_pattern_1mib_roundtrip_verified':True,'phone_ip':'169.254.42.1'},indent=2)+'\n')
    print('PASS: automatic SSH after boot; unchanged other partitions; 1MiB binary roundtrip')
else:
    raise SystemExit('use preflight | bootloader | flash | verify')
