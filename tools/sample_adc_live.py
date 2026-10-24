"""Bounded read-only ADC repeated-conversion test."""
from pathlib import Path
import subprocess
import time
from prepare_native_install import SSH
args = SSH[:]
args[-1] = 'penguin@172.16.42.1'
args = [x if not x.startswith('UserKnownHostsFile=') else 'UserKnownHostsFile=out/native-install-20261017/known_hosts' for x in args]
cmd = '''set -eu
cat /proc/sys/kernel/random/boot_id
for i in $(seq 1 15); do
 printf 'SAMPLE %s ' "$i"
 cat /sys/bus/iio/devices/iio:device0/in_temp1868_input
 sleep 1
done
cat /sys/class/power_supply/bq28z610-0/capacity /sys/class/power_supply/bq28z610-0/current_now /sys/class/power_supply/bq28z610-0/temp
journalctl -b -k --no-pager | grep -Ei 'adc5|conversion fault|conversion.*timed out|unknown symbol' || true
'''
p = subprocess.run(args + [cmd], capture_output=True, timeout=35)
dest = Path('out/native-install-20261017/adc-gen3') / ('samples-' + time.strftime('%Y%m%d-%H%M%S') + '.txt')
dest.write_bytes(p.stdout + p.stderr)
print(p.stdout.decode(errors='replace'))
print(p.stderr.decode(errors='replace'))
p.check_returncode()
