"""Stream a bounded physical-touch capture, save logs and restore color bars."""
import hashlib
import argparse
import json
import re
import subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser()
parser.add_argument('--seconds',type=int,default=60,choices=range(10,121))
args=parser.parse_args()
OUT=ROOT/'out/touch-port-20261013'
KEYS=ROOT/'out/usb-ncm-20261013/ssh'
SSH=['C:/Windows/System32/OpenSSH/ssh.exe','-F','none','-T','-i',str(KEYS/'client_key_host'),
     '-o','BatchMode=yes','-o','IdentitiesOnly=yes','-o','StrictHostKeyChecking=yes',
     '-o',f'UserKnownHostsFile={KEYS/"known_hosts"}','-o','ConnectTimeout=5',
     '-o','ServerAliveInterval=5','root@169.254.42.1']
def checked(cmd,data=None):
    p=subprocess.run(SSH+[cmd],input=data,capture_output=True,timeout=30)
    (OUT/'capture-last-stderr.txt').write_bytes(p.stderr)
    p.check_returncode();return p.stdout
data=(OUT/'touch-capture').read_bytes()
assert checked('cat > /tmp/touch-capture; chmod 700 /tmp/touch-capture; sha256sum /tmp/touch-capture',data).decode().split()[0]==hashlib.sha256(data).hexdigest()
with (OUT/'touch-events.txt').open('wb') as log:
    p=subprocess.Popen(SSH+[f'/tmp/touch-capture --seconds {args.seconds}'],stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
    try:
        for line in p.stdout:
            log.write(line);log.flush()
            # Save every frame, print only readiness and final result.
            if not line.startswith(b'FRAME '):print(line.decode(errors='replace'),end='',flush=True)
        rc=p.wait(timeout=10)
    finally:
        if p.poll() is None:p.terminate();p.wait(timeout=10)
        checked('/tmp/fb-pattern')
(OUT/'touch-dmesg-after-events.txt').write_bytes(checked('dmesg'))
(OUT/'touch-interrupts-after-events.txt').write_bytes(checked('cat /proc/interrupts'))
events=(OUT/'touch-events.txt').read_text()
match=re.search(r'SUMMARY frames=(\d+) max_contacts=(\d+)',events)
if rc or not match:raise SystemExit(f'Touch capture failed: {rc}; inspect touch-events.txt')
result=json.loads((OUT/'input-result.json').read_text())
result.update(physical_touch_events_verified=True,frames=int(match[1]),max_contacts=int(match[2]))
(OUT/'input-result.json').write_text(json.dumps(result,indent=2)+'\n')
print('PASS: real evdev touch frames captured and color bars restored',flush=True)
