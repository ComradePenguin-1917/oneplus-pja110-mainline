from pathlib import Path
import subprocess, time
from prepare_native_install import SSH
args = SSH[:]
args[-1] = 'penguin@172.16.42.1'
args = [x if not x.startswith('UserKnownHostsFile=') else 'UserKnownHostsFile=out/native-install-20261017/known_hosts' for x in args]
cmd = '''uname -a
cat /proc/sys/kernel/random/boot_id /proc/uptime
cat /sys/module/qcom_battmgr/parameters/pja110_charger_init
systemctl status pja110-battmgr-readonly.service --no-pager
for p in /sys/class/power_supply/*; do echo SUPPLY=$p; cat $p/uevent; done
journalctl -b -k --no-pager | grep -Ei 'battmgr|unknown symbol|charger|invalid|notification'
'''
p = subprocess.run(args + [cmd], capture_output=True, timeout=25)
dest = Path('out/native-install-20261017/charger-init-candidate') / ('live-' + time.strftime('%Y%m%d-%H%M%S') + '.txt')
dest.write_bytes(p.stdout + p.stderr)
print('EXIT', p.returncode, dest)
print(p.stdout.decode(errors='replace'))
print(p.stderr.decode(errors='replace'))
