"""Reload the runtime touch module, preserving the verified display and SPI."""
import hashlib
import json
import subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'out/touch-port-20261013'
KEYS=ROOT/'out/usb-ncm-20261013/ssh'
SSH=['C:/Windows/System32/OpenSSH/ssh.exe','-F','none','-T','-i',str(KEYS/'client_key_host'),
     '-o','BatchMode=yes','-o','IdentitiesOnly=yes','-o','StrictHostKeyChecking=yes',
     '-o',f'UserKnownHostsFile={KEYS/"known_hosts"}','-o','ConnectTimeout=5',
     '-o','ServerAliveInterval=5','root@169.254.42.1']
def run(cmd,data=None):
    p=subprocess.run(SSH+[cmd],input=data,capture_output=True,timeout=40)
    (OUT/'input-last-stderr.txt').write_bytes(p.stderr)
    p.check_returncode()
    return p.stdout
assert b'#14 SMP' in run('uname -a')
data=(OUT/'mainline_touch_probe.ko').read_bytes()
assert run('cat > /tmp/mainline_touch_input.ko; sha256sum /tmp/mainline_touch_input.ko',data).decode().split()[0]==hashlib.sha256(data).hexdigest()
response=run('rmmod mainline_touch_probe && insmod /tmp/mainline_touch_input.ko enable_touch=1')
(OUT/'input-module-load.txt').write_bytes(response)
log=run('dmesg')
(OUT/'input-dmesg.txt').write_bytes(log)
(OUT/'input-devices.txt').write_bytes(run('cat /proc/bus/input/devices; ls -l /sys/bus/spi/devices; cat /proc/interrupts'))
for line in log.decode(errors='replace').splitlines():
    if 'PJA_TOUCH' in line:print(line,flush=True)
assert b'PJA_TOUCH input enabled:' in log
assert b'PJA110 Synaptics S3910' in (OUT/'input-devices.txt').read_bytes()
(OUT/'input-result.json').write_text(json.dumps({'module_sha256':hashlib.sha256(data).hexdigest(),
    'input_device_registered':True,'physical_touch_events_verified':False,'partition_writes':False},indent=2)+'\n')
print('PASS: S3910 input device registered; physical finger events still required',flush=True)
