"""Read the factory BCC temperature diagnostic result."""
from pathlib import Path
import subprocess
import time
from prepare_native_install import SSH
args = SSH[:]
args[-1] = 'penguin@172.16.42.1'
args = [x if not x.startswith('UserKnownHostsFile=') else 'UserKnownHostsFile=out/native-install-20261017/known_hosts' for x in args]
cmd = '''uname -r
cat /proc/sys/kernel/random/boot_id /proc/uptime
cat /home/penguin/temp-readback/result.log
ls /sys/module/qcom_battmgr/parameters
systemctl is-active pja110-boot-success.service
cat /sys/bus/iio/devices/iio:device0/in_temp1868_input
cat /sys/class/power_supply/bq28z610-0/uevent
journalctl -b -k --no-pager | grep -Ei 'BCC matched-temp|BCC response:|notification/charger initialization stopped|conversion fault' || true
'''
p = subprocess.run(args + [cmd], capture_output=True, timeout=30)
dest = Path('out/native-install-20261017/temperature-readback') / ('live-' + time.strftime('%Y%m%d-%H%M%S') + '.txt')
dest.write_bytes(p.stdout + p.stderr)
print(p.stdout.decode(errors='replace'))
print(p.stderr.decode(errors='replace'))
print('Saved:', dest, 'SSH exit:', p.returncode)
p.check_returncode()
