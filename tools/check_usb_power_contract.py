"""Read USB link/descriptor power and supply state without reconfiguration."""
from pathlib import Path
import subprocess
import time
from prepare_native_install import SSH

args = SSH[:]
args[-1] = 'penguin@172.16.42.1'
args = [x if not x.startswith('UserKnownHostsFile=') else
        'UserKnownHostsFile=out/native-install-20261017/known_hosts' for x in args]
cmd = '''cat /proc/sys/kernel/random/boot_id /proc/uptime
echo UDC
for d in /sys/class/udc/*; do
    [ -d "$d" ] || continue
    for n in state current_speed maximum_speed is_selfpowered; do
        [ -r "$d/$n" ] || continue
        echo "$d/$n"
        cat "$d/$n"
    done
done
echo GADGET
for f in /sys/kernel/config/usb_gadget/*/configs/*/MaxPower /sys/kernel/config/usb_gadget/*/configs/*/bmAttributes; do
    [ -r "$f" ] || continue
    echo "$f"
    cat "$f"
done
echo TYPEC
echo DWC3_DT
test -d /sys/firmware/devicetree/base/soc@0/usb@a6f8800/usb@a600000 && echo DWC3_NODE_PRESENT
for n in usb-psy-name usb-phy phys phy-names; do
    f=/sys/firmware/devicetree/base/soc@0/usb@a6f8800/usb@a600000/$n
    [ -r "$f" ] || continue
    echo PROPERTY=$n
    od -An -tx1 "$f"
done
for d in /sys/class/typec/*; do
    [ -d "$d" ] || continue
    for n in power_operation_mode power_role data_role usb_power_delivery_revision; do
        [ -r "$d/$n" ] || continue
        echo "$d/$n"
        cat "$d/$n"
    done
done
echo USB_SUPPLY
cat /sys/class/power_supply/qcom-battmgr-usb/uevent
echo BATTERY
cat /sys/class/power_supply/bq28z610-0/uevent
echo RECENT_USB_LOG
journalctl -b -k --no-pager -n 80 | grep -Ei 'enumerat|super.speed|high.speed|usb.*(suspend|reset|disconnect)|ucsi|typec' | tail -n 35 || true
echo BOOT_SUCCESS
systemctl status pja110-boot-success.service --no-pager || true
echo USB_CONFIGURATION_SOURCE
for d in /etc/usb-moded /etc/conf.d; do
    [ -d "$d" ] || continue
    grep -RniE 'maxpower|max_power|usb-psy' "$d" 2>/dev/null || true
done
echo INPUT_LIMIT_ACCESS
ls -l /sys/class/power_supply/qcom-battmgr-usb/input_current_limit
echo SHORT_SAMPLE
for i in 1 2 3; do
    cat /proc/uptime
    for n in voltage_now current_now charge_now capacity; do
        printf 'BQ_%s=' "$n"
        cat /sys/class/power_supply/bq28z610-0/$n
    done
    printf 'USB_CURRENT='
    cat /sys/class/power_supply/qcom-battmgr-usb/current_now
    sleep 2
done
'''
p = subprocess.run(args + [cmd], capture_output=True, timeout=30)
dest = Path('out/native-install-20261017/charger-policy-audit') / (
    'usb-contract-' + time.strftime('%Y%m%d-%H%M%S') + '.txt')
dest.write_bytes(p.stdout + p.stderr)
print(p.stdout.decode(errors='replace'))
print(p.stderr.decode(errors='replace'))
print('Saved:', dest)
p.check_returncode()
