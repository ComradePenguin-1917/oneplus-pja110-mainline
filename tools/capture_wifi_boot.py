"""Preserve full clean-boot Wi-Fi diagnostics without changing phone state."""
from pathlib import Path
import subprocess
import time
from prepare_native_install import SSH

args = SSH[:]
args[-1] = 'penguin@172.16.42.1'
args = [x if not x.startswith('UserKnownHostsFile=') else
        'UserKnownHostsFile=out/native-install-20261017/known_hosts' for x in args]
cmd = '''boot_id=$(cat /proc/sys/kernel/random/boot_id)
printf '%s\n' "$boot_id"
cat /proc/uptime
echo WIFI_CAPTURE_STATE
systemctl show pja110-wifi-clean-boot.service -p ActiveState -p Result
cat /sys/module/ath12k/parameters/debug_mask
ls -l /home/penguin/wifi-bringup/clean-boot/complete /etc/modprobe.d/pja110-wifi-oneboot.conf 2>/dev/null || true
sha256sum /usr/lib/firmware/ath12k/WCN7850/hw2.0/*
echo WIFI_CAPTURE_COLLECTED
if grep -qx "$boot_id" /home/penguin/wifi-bringup/clean-boot/result.txt 2>/dev/null; then
 cat /home/penguin/wifi-bringup/clean-boot/result.txt
else
 echo 'Collector result not ready for this boot; current journal follows'
fi
echo WIFI_CAPTURE_CURRENT
journalctl -b -k --no-pager
'''
p = subprocess.run(args + [cmd], capture_output=True, timeout=35)
dest = Path('out/wifi-bringup-20261017') / ('full-boot-' + time.strftime('%Y%m%d-%H%M%S') + '.txt')
dest.write_bytes(p.stdout+p.stderr)
p.check_returncode()
print('Saved:', dest)
print(p.stdout.decode(errors='replace').split('WIFI_CAPTURE_COLLECTED')[0])
