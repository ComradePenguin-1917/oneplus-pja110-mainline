"""Stage an A-native, reboot-only duplicate battery correction and rollback."""
import hashlib
import json
from pathlib import Path

from stage_wifi_native_test import run

OUT = Path('out/battery-upower-20261017/candidate')
REMOTE = '/home/penguin/single-battery'
manifest = json.loads((OUT / 'manifest.json').read_text())
module = (OUT / 'qcom_battmgr.ko').read_bytes()
assert hashlib.sha256(module).hexdigest() == manifest['sha256']
previous = '25646e3863ff0cf0e7c2ed776bacc56d6cbd5b97ee2d3fd740d17172f9fad851'
install = '''#!/bin/sh
set -eu
test "$(id -u)" = 0
cd /home/penguin/single-battery
test "$(sha256sum qcom_battmgr.ko | cut -d ' ' -f 1)" = NEW_SHA
test "$(modinfo -F version ./qcom_battmgr.ko)" = pja110-single-battery-1
test "$(uname -r)" = 6.14.0-oneplus-xigua
test -e /sys/class/power_supply/bq28z610-0/capacity
test "$(cat /sys/class/power_supply/bq28z610-0/capacity)" -ge 20
test "$(cat /sys/module/qcom_battmgr/parameters/pja110_charger_init)" = N
dest=/usr/local/lib/pja110/qcom_battmgr.ko
test "$(sha256sum "$dest" | cut -d ' ' -f 1)" = OLD_SHA
systemctl is-enabled pja110-battmgr-readonly.service
save=/var/lib/pja110-single-battery
mkdir -p "$save"
if [ ! -e "$save/qcom_battmgr-before.ko" ]; then
 cp -p "$dest" "$save/qcom_battmgr-before.ko"
fi
test "$(sha256sum "$save/qcom_battmgr-before.ko" | cut -d ' ' -f 1)" = OLD_SHA
upower -d > "$save/upower-before.txt"
cat /sys/class/power_supply/bq28z610-0/uevent > "$save/bq-before.txt"
install -m 644 qcom_battmgr.ko "$dest"
test "$(sha256sum "$dest" | cut -d ' ' -f 1)" = NEW_SHA
sync
echo 'Single-battery module installed; original backed up; normal reboot, no hot unload'
systemctl reboot
'''.replace('NEW_SHA', manifest['sha256']).replace('OLD_SHA', previous)
restore = '''#!/bin/sh
set -eu
test "$(id -u)" = 0
save=/var/lib/pja110-single-battery
test "$(sha256sum "$save/qcom_battmgr-before.ko" | cut -d ' ' -f 1)" = OLD_SHA
install -m 644 "$save/qcom_battmgr-before.ko" /usr/local/lib/pja110/qcom_battmgr.ko
sync
systemctl reboot
'''.replace('OLD_SHA', previous)
run('mkdir -p ' + REMOTE)
for name, data in {'qcom_battmgr.ko': module, 'install.sh': install.encode(), 'restore.sh': restore.encode()}.items():
    (OUT / name).write_bytes(data)
    run('cat > ' + REMOTE + '/' + name, data)
result = run(f'cd {REMOTE}; sh -n install.sh; sh -n restore.sh; sha256sum qcom_battmgr.ko; modinfo -F version ./qcom_battmgr.ko')
(OUT / 'staging.txt').write_bytes(result)
assert manifest['sha256'].encode() in result
print(result.decode())
manifest['phone_staged'] = True
(OUT / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
