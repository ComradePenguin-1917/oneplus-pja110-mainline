"""Verify NCM/SSH returns after a real reboot without runtime bootstrapping."""
import json
import subprocess
import time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'out/debug-ncm-fixed-20261013'
SSH=ROOT/'out/usb-ncm-20261013/ssh'
command=['C:/Windows/System32/OpenSSH/ssh.exe','-F','none','-T','-i',str(SSH/'client_key_host'),
         '-o','BatchMode=yes','-o','IdentitiesOnly=yes','-o','StrictHostKeyChecking=yes',
         '-o',f'UserKnownHostsFile={SSH/"known_hosts"}','-o','ConnectTimeout=3','root@169.254.42.1']
def remote(cmd): return subprocess.run(command+[cmd],capture_output=True,timeout=8)
assert json.loads((OUT/'result.json').read_text())['automatic_ssh_verified']
before=remote('cat /proc/sys/kernel/random/boot_id; cat /proc/uptime')
before.check_returncode()
(OUT/'reboot-before.txt').write_bytes(before.stdout)
started=time.monotonic()
request=remote('reboot -f')
(OUT/'reboot-request.txt').write_bytes(request.stdout+request.stderr)
time.sleep(4)
while time.monotonic()-started<90:
    after=remote('cat /proc/sys/kernel/random/boot_id; cat /proc/uptime; id; cat /tmp/debug-ssh.log; cat /sys/class/udc/*/state')
    if after.returncode==0 and after.stdout.splitlines()[0]!=before.stdout.splitlines()[0]:
        assert b'uid=0(root)' in after.stdout and b'configured' in after.stdout
        (OUT/'reboot-after.txt').write_bytes(after.stdout)
        result={'automatic_ssh_after_second_boot':True,'boot_id_changed':True,
                'elapsed_seconds':round(time.monotonic()-started,2)}
        (OUT/'reboot-result.json').write_text(json.dumps(result,indent=2)+'\n')
        print('PASS: real reboot changed boot_id; NCM/SSH returned automatically',flush=True)
        break
    time.sleep(3)
else:
    (OUT/'reboot-error.txt').write_bytes(after.stdout+after.stderr)
    raise SystemExit('SSH did not return after reboot; check device state')
