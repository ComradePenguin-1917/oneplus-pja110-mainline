"""Stage one admin operation: persistent A success and one-shot temperature test."""
from pathlib import Path
import hashlib
import subprocess
from prepare_native_install import SSH
root = Path(__file__).resolve().parents[1]
out = root / 'out/native-install-20261017/temperature-handoff'
args = SSH[:]
args[-1] = 'penguin@172.16.42.1'
args = [x if not x.startswith('UserKnownHostsFile=') else 'UserKnownHostsFile=out/native-install-20261017/known_hosts' for x in args]
def run(cmd, data=None):
    p = subprocess.run(args + [cmd], input=data, capture_output=True, timeout=30)
    print(p.stdout.decode(errors='replace'), end='')
    print(p.stderr.decode(errors='replace'), end='')
    p.check_returncode()
    return p.stdout
run('umask 077; mkdir -p /home/penguin/boot-temp-test; systemctl is-active sshd.service greetd.service; pgrep -x phoc; sudo -n true 2>/dev/null && echo ADMIN_AVAILABLE || true')
files = {
    'qbootctl': root / 'out/boot-success-20261014/qbootctl-aarch64',
    'mark-a-success.sh': root / 'tools/pja110-mark-a-success.sh',
    'pja110-boot-success.service': root / 'tools/pja110-boot-success.service',
    'qcom_battmgr-temperature.ko': out / 'qcom_battmgr-temperature.ko',
}
digests = {}
for name, path in files.items():
    data = path.read_bytes()
    if name.endswith(('.sh', '.service')):
        data = data.replace(b'\r\n', b'\n')
    digests[name] = hashlib.sha256(data).hexdigest()
    result = run('cat > /home/penguin/boot-temp-test/' + name + ' && sha256sum /home/penguin/boot-temp-test/' + name, data)
    assert result.decode().split()[0] == digests[name]
checks = ''.join(digest + '  ' + name + '\n' for name, digest in digests.items())
script = '''#!/bin/sh
set -eu
umask 077
cd /home/penguin/boot-temp-test
exec > result.log 2>&1
chmod 644 result.log
cat > SHA256SUMS <<'HASHES'
@CHECKS@HASHES
sha256sum -c SHA256SUMS
test "$(uname -r)" = 6.14.0-oneplus-xigua
install -D -m 755 qbootctl /usr/local/libexec/pja110-qbootctl
install -D -m 755 mark-a-success.sh /usr/local/libexec/pja110-mark-a-success
install -m 644 pja110-boot-success.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable pja110-boot-success.service
systemctl start pja110-boot-success.service
systemctl status pja110-boot-success.service --no-pager
echo BOOT_SUCCESS_STAGE_COMPLETE

# Only test one factory matched-temperature write; restore read-only module.
test -f /usr/local/lib/pja110/qcom_battmgr.ko
label=/sys/bus/iio/devices/iio:device0/in_temp1868_label
sensor=/sys/bus/iio/devices/iio:device0/in_temp1868_input
test "$(cat "$label")" = subboard_temp
adc=$(cat "$sensor")
bq=$(cat /sys/class/power_supply/bq28z610-0/temp)
test "$adc" -ge 10000 && test "$adc" -le 40000
test "$bq" -ge 100 && test "$bq" -le 400
diff=$((adc / 100 - bq))
test "$diff" -ge -50 && test "$diff" -le 50
restore() {
    if [ -d /sys/module/qcom_battmgr ]; then
        rmmod qcom_battmgr || return 1
    fi
    insmod /usr/local/lib/pja110/qcom_battmgr.ko pja110_charger_init=0
}
rmmod qcom_battmgr
trap 'restore' EXIT
# Read again immediately before loading; no fallback on ADC failure.
adc=$(cat "$sensor")
test "$adc" -ge 10000 && test "$adc" -le 40000
insmod ./qcom_battmgr-temperature.ko pja110_match_temp=$((adc / 100))
for i in $(seq 1 10); do
    result=$(cat /sys/module/qcom_battmgr/parameters/temperature_result)
    [ "$result" = -115 ] || break
    sleep 1
done
echo "MATCH_TEMP_ADC_mC=$adc RESULT=$result"
test "$result" = 0
restore
trap - EXIT
echo TEMPERATURE_ONESHOT_ACK_OK_READONLY_RESTORED
cat /sys/class/power_supply/bq28z610-0/uevent
echo COMPLETE_NO_REBOOT_NO_CHARGE_ENABLE
'''
script = script.replace('@CHECKS@', checks)
(out / 'install-boot-temperature.sh').write_bytes(script.encode())
run('cat > /home/penguin/install-boot-temperature.sh', script.encode())
run('sh -n /home/penguin/install-boot-temperature.sh; sh -n /home/penguin/boot-temp-test/mark-a-success.sh')
print('Staged fixed admin operation; no sudo or reboot executed.')
