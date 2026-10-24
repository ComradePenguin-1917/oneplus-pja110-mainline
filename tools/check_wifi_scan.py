"""Read loaded module identity, automatic scan evidence and saved profile names."""
from pathlib import Path
import subprocess
import time
from prepare_native_install import SSH

args = SSH[:]
args[-1] = 'penguin@172.16.42.1'
args = [x if not x.startswith('UserKnownHostsFile=') else
        'UserKnownHostsFile=out/native-install-20261017/known_hosts' for x in args]
cmd = '''cat /proc/sys/kernel/random/boot_id
cat /sys/module/ath12k/version /sys/module/ath12k/srcversion
echo AUTO_SCAN_SERVICE
systemctl show pja110-wifi-aston-rfkill.service -p ActiveState -p Result
echo AUTO_SCAN_RESULT
cat /home/penguin/wifi-bringup/aston-rfkill/result.txt 2>/dev/null
echo CACHED_ACCESS_POINTS
nmcli -f IN-USE,SSID,MODE,CHAN,RATE,SIGNAL,SECURITY device wifi list ifname wlan0 --rescan no
echo PROFILES
nmcli -t -f NAME,TYPE,DEVICE connection show
echo IP_ADDRESSES
ip -brief address show wlan0
echo PERMISSIONS
nmcli general permissions
'''
p = subprocess.run(args + [cmd], capture_output=True, timeout=30)
dest = Path('out/wifi-bringup-20261017') / ('scan-' + time.strftime('%Y%m%d-%H%M%S') + '.txt')
dest.write_bytes(p.stdout+p.stderr)
print(p.stdout.decode(errors='replace'))
print(p.stderr.decode(errors='replace'))
print('Saved:', dest)
p.check_returncode()
