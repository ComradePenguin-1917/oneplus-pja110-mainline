"""Read-only check of installed power modules, boot identity, and sudo access."""
from pathlib import Path
import subprocess
from prepare_native_install import SSH

args = SSH[:]
args[-1] = 'penguin@172.16.42.1'
args = [x if not x.startswith('UserKnownHostsFile=') else
        'UserKnownHostsFile=out/native-install-20261017/known_hosts' for x in args]
cmd = '''cat /proc/cmdline
cat /sys/class/power_supply/bq28z610-0/capacity
for m in pci_pwrctrl_pwrseq pwrseq_qcom_wcn ath12k; do modinfo "$m" | head -n 16; done
ls -l /dev/disk/by-partlabel/vendor_boot_a
nmcli general permissions
sudo -n true
'''
p = subprocess.run(args + [cmd], capture_output=True, timeout=25)
Path('out/wifi-bringup-20261017/access.txt').write_bytes(p.stdout + p.stderr)
print(p.stdout.decode(errors='replace'))
print(p.stderr.decode(errors='replace'))
print('Command exit:', p.returncode)
