"""Read back recovery partitions and freeze the restored simultaneous baseline."""
import hashlib,json,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'out/boot-recovery-diagnosis-20261014'
KEYS=ROOT/'out/usb-ncm-20261013/ssh'
SSH=['C:/Windows/System32/OpenSSH/ssh.exe','-F','none','-T','-i',str(KEYS/'client_key_host'),
 '-o','BatchMode=yes','-o','IdentitiesOnly=yes','-o','StrictHostKeyChecking=yes',
 '-o',f'UserKnownHostsFile={KEYS/"known_hosts"}','-o','ConnectTimeout=5','root@169.254.42.1']
def read(cmd):
 p=subprocess.run(SSH+[cmd],capture_output=True,timeout=90);p.check_returncode();return p.stdout
expected=json.loads((ROOT/'out/aston-touch-240hz-20261013/verified-autostart/autostart-device-after.json').read_text())
expected['boot_b']=hashlib.sha256((OUT/'boot_b-working-restored-avb.img').read_bytes()).hexdigest()
actual={}
for part in expected:
 raw=read('for f in /sys/class/block/sd*/uevent; do cat "$f"; echo END; done').decode()
 found=[]
 for record in raw.split('END'):
  props=dict(line.split('=',1) for line in record.splitlines() if '=' in line)
  if props.get('PARTNAME')==part:found.append(props['DEVNAME'])
 assert len(found)==1
 actual[part]=read('sha256sum /dev/'+found[0]).decode().split()[0]
assert actual==expected,(actual,expected)
state=read('uname -a; cat /proc/uptime; cat /tmp/touch-init.log; cat /proc/bus/input/devices; cat /sys/module/synaptics_aston/parameters/report_rate_code; cat /sys/class/drm/card0-DSI-1/status; dmesg')
assert b'#14 SMP' in state and b'PJA_ASTON fixed report rate code=3 readback verified' in state
assert b'AA536 60 Hz initialization complete' in state
(OUT/'recovered-state.txt').write_bytes(state)
(OUT/'recovered-partition-hashes.json').write_text(json.dumps(actual,indent=2)+'\n')
manifest=json.loads((OUT/'boot-repair-manifest.json').read_text())
manifest.update(phone_execution_confirmed=True,all_eight_partitions_verified=True,
 user_confirmed_normal_color_bars=True,ssh_and_aston_240hz_restored=True)
(OUT/'boot-repair-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
print('PASS: restored #14 display + Aston 240Hz + SSH baseline; all eight partition hashes verified')
