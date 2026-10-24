"""Read results of the fixed administrator boot/temperature operation."""
from pathlib import Path
import subprocess
import time
from prepare_native_install import SSH
args = SSH[:]
args[-1] = 'penguin@172.16.42.1'
args = [x if not x.startswith('UserKnownHostsFile=') else 'UserKnownHostsFile=out/native-install-20261017/known_hosts' for x in args]
cmd = '''uname -a
cat /proc/sys/kernel/random/boot_id /proc/uptime
cat /home/penguin/boot-temp-test/result.log
systemctl status pja110-boot-success.service --no-pager
systemctl is-enabled pja110-boot-success.service
ls /sys/module/qcom_battmgr/parameters
cat /sys/class/power_supply/bq28z610-0/uevent
cat /sys/bus/iio/devices/iio:device0/in_temp1868_input
journalctl -b -k --no-pager | grep -Ei 'matched temperature|AP gauge check|notification/charger|adc5|conversion fault' || true
echo ADMIN_EXECUTION_HISTORY
journalctl -b --no-pager -t sudo -t sudo-rs | tail -n 50
'''
p = subprocess.run(args + [cmd], capture_output=True, timeout=30)
out = Path('out/native-install-20261017/temperature-handoff')
dest = out / ('live-' + time.strftime('%Y%m%d-%H%M%S') + '.txt')
dest.write_bytes(p.stdout + p.stderr)
print(p.stdout.decode(errors='replace'))
print(p.stderr.decode(errors='replace'))
print('Saved:', dest, 'SSH exit:', p.returncode)
p.check_returncode()
