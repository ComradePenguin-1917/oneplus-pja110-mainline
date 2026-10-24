"""Capture current native phone state with pinned SSH identity; no root required."""
import argparse
import json
import subprocess
import time
from pathlib import Path

from prepare_native_install import SSH

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='10.4.183.195', help='Phone IPv4 or hostname; DHCP address may change')
    options = parser.parse_args()
    if options.host.startswith('-') or any(c.isspace() for c in options.host):
        parser.error('Invalid host')
    args = [x if not x.startswith('UserKnownHostsFile=') else
            f'UserKnownHostsFile={ROOT / "out/native-install-20261017/known_hosts"}' for x in SSH]
    args[-1:] = ['-o', 'HostKeyAlias=172.16.42.1', 'penguin@' + options.host]
    command = '''echo IDENTITY
date -Is; uname -a; cat /proc/sys/kernel/random/boot_id
cat /proc/cmdline; cat /proc/1/comm
echo FILESYSTEMS
findmnt /; findmnt /boot; df -Pk / /boot
echo NETWORK
printf 'SSH_CONNECTION=%s\\n' "$SSH_CONNECTION"
ip -brief address; ip route
nmcli -t -f DEVICE,TYPE,STATE device
echo LOCAL_PACKAGES
apk --no-network info -v | grep -E '^(linux-oneplus-xigua|device-oneplus-xigua|firmware-oneplus-xigua|phoc)-'
echo WIFI
cat /sys/module/ath12k/version /sys/module/ath12k/srcversion
modinfo -F filename ath12k; rfkill list
echo POWER
for d in /sys/class/power_supply/*; do echo DEVICE="$d"; cat "$d/uevent"; done
cat /sys/module/qcom_battmgr/version
upower -d
echo DISPLAY_INPUT
for f in /sys/class/drm/card*-DSI-*/status /sys/class/drm/card*-DSI-*/modes; do
 if [ -f "$f" ]; then echo FILE="$f"; cat "$f"; fi
done
cat /proc/bus/input/devices
pgrep -a phoc; pgrep -a phosh
echo LOCAL_SERVICES
systemctl list-unit-files --no-pager | grep -E '^pja110'
for s in pja110-boot-success pja110-battmgr-readonly pja110-adc-test; do
 systemctl cat "$s.service" --no-pager 2>/dev/null || true
done
echo ADC
for d in /sys/bus/iio/devices/iio:device*; do
 test -d "$d" || continue
 echo DEVICE="$d"; cat "$d/name"
 for f in "$d"/in_temp*_input; do test ! -f "$f" || cat "$f"; done
done
echo MODULES
lsmod
echo FAILED_SERVICES
systemctl --failed --no-pager
echo WARNINGS
journalctl -b -k -p warning --no-pager | tail -n 100
'''
    result = subprocess.run(args + [command], capture_output=True, timeout=60)
    out = ROOT / 'out/maintenance-20261017'
    out.mkdir(exist_ok=True)
    path = out / ('phone-state-' + time.strftime('%Y%m%d-%H%M%S') + '.txt')
    path.write_bytes(result.stdout + result.stderr)
    print(json.dumps({'host': options.host, 'exit_code': result.returncode,
                      'capture': str(path)}, ensure_ascii=False))
    result.check_returncode()


if __name__ == '__main__':
    main()
