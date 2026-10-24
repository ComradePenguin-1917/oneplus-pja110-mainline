"""Read-only Type-C, power-supply and charger telemetry snapshot."""
from pathlib import Path
import subprocess, time
from prepare_native_install import SSH
ROOT=Path(__file__).resolve().parents[1]
args=SSH[:]
args[-1]='penguin@172.16.42.1'
args=[x if not x.startswith('UserKnownHostsFile=') else 'UserKnownHostsFile=out/native-install-20261017/known_hosts' for x in args]
cmd='''set +e
echo IDENTITY; uname -a; cat /proc/sys/kernel/random/boot_id
echo TYPEC
for d in /sys/class/typec/port0 /sys/class/typec/port0-partner /sys/class/typec/port0-partner/*; do
 [ -d "$d" ] || continue; echo DEVICE=$d
 find "$d" -maxdepth 1 -type f -printf '%f=' -exec cat {} \\; 2>/dev/null
done
echo POWER
for d in /sys/class/power_supply/*; do [ -d "$d" ] || continue; echo DEVICE=$d; cat "$d/uevent"; done
echo BATTERY_THERMAL
cat /sys/class/power_supply/bq28z610-0/temp /sys/class/power_supply/bq28z610-0/capacity /sys/class/power_supply/bq28z610-0/current_now /sys/class/power_supply/bq28z610-0/voltage_now 2>/dev/null
echo LOG
journalctl -b -k --no-pager | grep -Ei 'typec|ucsi|tcpm|power.deliver|pd|pps|charger|battmgr|adsp' | tail -n 160
echo END
'''
p=subprocess.run(args+[cmd],capture_output=True,timeout=40)
out=ROOT/'out/native-install-20261017/charger-policy-audit'
out.mkdir(parents=True,exist_ok=True)
path=out/('fastcharge-readonly-'+time.strftime('%Y%m%d-%H%M%S')+'.txt')
path.write_bytes(p.stdout+p.stderr)
print(p.stdout.decode(errors='replace')); print('Saved:',path,'SSH exit:',p.returncode)
p.check_returncode()
