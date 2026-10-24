from pathlib import Path
import subprocess
from prepare_native_install import SSH
args = SSH[:]
args[-1] = 'penguin@172.16.42.1'
args = [x if not x.startswith('UserKnownHostsFile=') else 'UserKnownHostsFile=out/native-install-20261017/known_hosts' for x in args]
cmd = '''uname -a
cat /proc/sys/kernel/random/boot_id /proc/uptime
od -An -tc /sys/firmware/devicetree/base/compatible
cat /sys/class/power_supply/*/uevent
journalctl -b -k --no-pager | grep -Ei 'PDM:|pd_mapper|charger|adsp|pmic.glink'
'''
p = subprocess.run(args + [cmd], capture_output=True, timeout=20)
Path('out/native-install-20261017/dtbo-mainline-identity/runtime-a.txt').write_bytes(p.stdout + p.stderr)
print('EXIT', p.returncode)
print(p.stdout.decode(errors='replace'))
print(p.stderr.decode(errors='replace'))
