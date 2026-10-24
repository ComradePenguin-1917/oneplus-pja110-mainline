"""Read and save evidence from the compiled Wi-Fi/kernel native boot."""
import json
from pathlib import Path

from stage_wifi_native_test import OUT, run

command = '''uname -a
cat /proc/sys/kernel/random/boot_id
cat /proc/cmdline
findmnt /
apk --no-network info -v | grep -E '^(linux-oneplus-xigua|device-oneplus-xigua|firmware-oneplus-xigua-wifi)-'
modinfo -F filename ath12k
cat /sys/module/ath12k/version /sys/module/ath12k/srcversion
sha256sum /boot/vmlinuz
echo INSTALL_LOG
cat /home/penguin/wifi-bringup/native-test/install.log
echo SERVICE_STATE
systemctl --failed --no-pager
systemctl list-units --all --no-pager | grep -Ei 'boot.*success|success.*boot' || true
pgrep -a phoc
pgrep -a phosh
echo TOUCH_CONFIG
cat /sys/module/synaptics_aston/parameters/* 2>/dev/null || true
echo POWER
for d in /sys/class/power_supply/*; do
 echo "$d"
 for f in capacity status current_now voltage_now online; do
  if [ -f "$d/$f" ]; then printf '%s=' "$f"; cat "$d/$f"; fi
 done
done
'''
data = run(command)
(OUT / 'native-after.txt').write_bytes(data)
text = data.decode(errors='replace')
manifest = json.loads((OUT / 'manifest.json').read_text())
assert 'Sat Oct 17 08:23:58 UTC 2026' in text
assert '/kernel/drivers/net/wireless/ath/ath12k/ath12k.ko' in text
assert manifest['kernel_sha256'] in text
for name in ['boot_b', 'init_boot_b', 'vendor_boot_b', 'dtbo_b']:
    assert '/dev/disk/by-partlabel/' + name + ': OK' in text
assert 'NATIVE_WIFI_APKS_AND_BOOT_A_VERIFIED' in text
assert '0 loaded units listed.' in text
result = dict(boot_id=text.splitlines()[1], compiled_kernel_native_boot_verified=True,
              packaged_ath12k_loaded=True, legacy_wifi_override_removed=True,
              rescue_b_unchanged_verified_at_install=True,
              desktop_touch_and_smoothness_user_confirmed=True,
              wireless_round_trip_evidence='out/wifi-bringup-20261017/wireless-ssh-20261017-163747.json',
              existing_rootfs_preserved=True, exported_fresh_rootfs_native_boot_tested=False)
(OUT / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
manifest['installed'] = True
manifest['native_boot_verified'] = True
(OUT / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
print(text[:1100])
print(json.dumps(result, indent=2))
