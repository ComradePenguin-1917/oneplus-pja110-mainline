"""Stage a bounded factory BCC readback, never invoke remote sudo."""
from pathlib import Path
import hashlib
import subprocess
from prepare_native_install import SSH
out = Path('out/native-install-20261017/temperature-readback')
args = SSH[:]
args[-1] = 'penguin@172.16.42.1'
args = [x if not x.startswith('UserKnownHostsFile=') else 'UserKnownHostsFile=out/native-install-20261017/known_hosts' for x in args]
def run(cmd, data=None):
    p = subprocess.run(args + [cmd], input=data, capture_output=True, timeout=30)
    print(p.stdout.decode(errors='replace'), end='')
    print(p.stderr.decode(errors='replace'), end='')
    p.check_returncode()
    return p.stdout
data = (out / 'qcom_battmgr-readback.ko').read_bytes()
sha = hashlib.sha256(data).hexdigest()
assert run('umask 077; mkdir -p /home/penguin/temp-readback; cat > /home/penguin/temp-readback/qcom_battmgr-readback.ko; sha256sum /home/penguin/temp-readback/qcom_battmgr-readback.ko', data).decode().split()[0] == sha
script = '''#!/bin/sh
set -eu
cd /home/penguin/temp-readback
exec > result.log 2>&1
chmod 644 result.log
test "$(uname -r)" = 6.14.0-oneplus-xigua
echo "@SHA@  qcom_battmgr-readback.ko" | sha256sum -c -
test -f /usr/local/lib/pja110/qcom_battmgr.ko
restore() {
    if [ -d /sys/module/qcom_battmgr ]; then
        rmmod qcom_battmgr || return 1
    fi
    insmod /usr/local/lib/pja110/qcom_battmgr.ko pja110_charger_init=0
}
cat /proc/sys/kernel/random/boot_id /proc/uptime
rmmod qcom_battmgr
trap restore EXIT
insmod ./qcom_battmgr-readback.ko
for i in $(seq 1 10); do
    result=$(cat /sys/module/qcom_battmgr/parameters/readback_result)
    [ "$result" = -115 ] || break
    sleep 1
done
echo "BCC_READ_RESULT=$result"
printf 'MATCHED_TEMP_dC='
cat /sys/module/qcom_battmgr/parameters/matched_temp
test "$result" = 0
restore
trap - EXIT
echo BCC_READBACK_COMPLETE_READONLY_RESTORED
'''
script = script.replace('@SHA@', sha)
(out / 'read-temperature.sh').write_bytes(script.encode())
run('cat > /home/penguin/read-temperature.sh', script.encode())
run('sh -n /home/penguin/read-temperature.sh; cat /sys/class/power_supply/bq28z610-0/capacity')
