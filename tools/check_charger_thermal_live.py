"""Read existing IIO and thermal interfaces without reconfiguration."""
from pathlib import Path
import subprocess
import time
from prepare_native_install import SSH
args = SSH[:]
args[-1] = 'penguin@172.16.42.1'
args = [x if not x.startswith('UserKnownHostsFile=') else
        'UserKnownHostsFile=out/native-install-20261017/known_hosts' for x in args]
cmd = '''uname -r
cat /proc/sys/kernel/random/boot_id /proc/uptime
echo IIO_BEGIN
for d in /sys/bus/iio/devices/iio:device*; do
    [ -d "$d" ] || continue
    echo DEVICE=$d
    cat "$d/name"
    ls "$d"
    for f in "$d"/in_temp*_label "$d"/in_temp*_input; do
        [ -f "$f" ] || continue
        echo ATTRIBUTE=$f
        cat "$f"
    done
done
echo THERMAL_BEGIN
for d in /sys/class/thermal/thermal_zone*; do
    [ -d "$d" ] || continue
    echo ZONE=$d
    cat "$d/type" "$d/temp"
done
echo GAUGE_BEGIN
cat /sys/class/power_supply/bq28z610-0/uevent
journalctl -b -k --no-pager | grep -Ei 'adc5|conversion|timed out|unknown symbol' || true
'''
p = subprocess.run(args + [cmd], capture_output=True, timeout=30)
dest = Path('out/native-install-20261017/charger-init-candidate') / ('thermal-live-' + time.strftime('%Y%m%d-%H%M%S') + '.txt')
dest.write_bytes(p.stdout + p.stderr)
print(p.stdout.decode(errors='replace'))
print(p.stderr.decode(errors='replace'))
print('Saved:', dest, 'SSH exit:', p.returncode)
p.check_returncode()
