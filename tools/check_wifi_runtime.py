"""Read-only Wi-Fi/PCIe inventory on native postmarketOS."""
from pathlib import Path
import subprocess
import time
from prepare_native_install import SSH

args = SSH[:]
args[-1] = 'penguin@172.16.42.1'
args = [x if not x.startswith('UserKnownHostsFile=') else
        'UserKnownHostsFile=out/native-install-20261017/known_hosts' for x in args]
cmd = '''uname -a
cat /proc/sys/kernel/random/boot_id /proc/uptime
ip -brief link
nmcli -t -f RUNNING,STATE general
nmcli -t -f DEVICE,TYPE,STATE device
rfkill list 2>/dev/null || true
ls /sys/bus/pci/devices
for d in /sys/bus/pci/devices/*; do
 [ -d "$d" ] || continue
 echo PCI=$d
 cat "$d/vendor" "$d/device" "$d/modalias"
 readlink "$d/driver" || true
done
lsmod | grep -E 'ath|mhi|pci|qcom|qrtr|cfg80211|mac80211' || true
modinfo ath12k 2>/dev/null | head -n 16
find /usr/lib/firmware /lib/firmware -maxdepth 5 -iname '*wcn*' -o -name 'board-2.bin' -o -name 'amss.bin' -o -name 'm3.bin' 2>/dev/null
journalctl -b -k --no-pager | grep -Ei 'ath12|wlan|wifi|wcn|pcie|pci |mhi|cnss|firmware' | tail -n 180
echo POWER
cat /sys/class/power_supply/bq28z610-0/capacity /sys/class/power_supply/bq28z610-0/current_now
'''
p = subprocess.run(args + [cmd], capture_output=True, timeout=40)
out = Path('out/wifi-bringup-20261017')
out.mkdir(exist_ok=True)
dest = out / ('runtime-' + time.strftime('%Y%m%d-%H%M%S') + '.txt')
dest.write_bytes(p.stdout + p.stderr)
print(p.stdout.decode(errors='replace'))
print(p.stderr.decode(errors='replace'))
print('Saved:', dest)
p.check_returncode()
