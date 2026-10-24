"""Stage signed Wi-Fi/kernel APKs and a guarded A-only native boot update."""
import gzip
import hashlib
import json
import subprocess
from pathlib import Path

from bootimg import BootImage
from package_native_pmos import avb_offset
from prepare_native_install import SSH

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'out/wifi-bringup-20261017/native-test'
REMOTE = '/home/penguin/wifi-bringup/native-test'
args = [x if not x.startswith('UserKnownHostsFile=') else
        'UserKnownHostsFile=out/native-install-20261017/known_hosts' for x in SSH]
args[-1:] = ['-o', 'HostKeyAlias=172.16.42.1', 'penguin@10.4.183.195']
sha = lambda data: hashlib.sha256(data).hexdigest()


def run(command, data=None, timeout=180):
    p = subprocess.run(args + [command], input=data, capture_output=True, timeout=timeout)
    if p.returncode:
        raise RuntimeError(p.stderr.decode(errors='replace') + p.stdout.decode(errors='replace'))
    return p.stdout


def main():
    source = ROOT / 'out/native-install-20261017/charger-startup/boot_a.img'
    old = source.read_bytes()
    assert sha(old) == 'c20408b2e4808b969c225d49af0052215e6e40695a5376f4fe49d6f5824689c8'
    boot = BootImage.parse(str(source))
    kernel = (OUT / 'vmlinuz').read_bytes()
    assert kernel[56:60] == b'ARM\x64'
    assert b'root=UUID=af27e4ed-0f1f-4976-94a1-46c4c658e55e' in boot.cmdline
    boot.kernel = kernel
    prefix = boot.pack(cmdline=boot.cmdline.decode())
    offset = avb_offset(old)
    assert len(prefix) < offset
    new = prefix + bytes(offset - len(prefix)) + old[offset:]
    (OUT / 'boot_a.img').write_bytes(new)
    parsed = BootImage.parse(str(OUT / 'boot_a.img'))
    assert parsed.kernel == kernel and parsed.cmdline == boot.cmdline
    (OUT / 'boot_a.img.gz').write_bytes(gzip.compress(new, compresslevel=1, mtime=0))
    script = '''#!/bin/sh
set -eu
test "$(id -u)" = 0
cd /home/penguin/wifi-bringup/native-test
sha256sum -c files.sha256
test "$(uname -r)" = 6.14.0-oneplus-xigua
grep -q 'root=UUID=af27e4ed-0f1f-4976-94a1-46c4c658e55e' /proc/cmdline
test "$(cat /sys/class/power_supply/bq28z610-0/capacity)" -ge 20
a=/dev/disk/by-partlabel/boot_a
test "$(sha256sum "$a" | cut -d ' ' -f 1)" = OLD_BOOT_SHA
test "$(cat /sys/class/block/$(basename "$(readlink -f "$a")")/size)" = 393216
save=/var/lib/pja110-wifi-native-test
mkdir -p "$save"
test ! -e "$save/update-started"
for n in boot_b init_boot_b vendor_boot_b dtbo_b; do
 sha256sum /dev/disk/by-partlabel/$n
done > "$save/b-before.sha256"
dd if="$a" of="$save/boot_a-before.img" bs=1048576
cp /etc/apk/world "$save/world-before"
cp /boot/vmlinuz "$save/vmlinuz-before"
apk --no-network verify ./*.apk
apk --no-network add --simulate ./linux-oneplus-xigua-6.14-r1.apk ./device-oneplus-xigua-1-r4.apk ./device-oneplus-xigua-phosh-1-r4.apk ./firmware-oneplus-xigua-wifi-1-r0.apk
gzip -dc boot_a.img.gz > boot_a.img
test "$(sha256sum boot_a.img | cut -d ' ' -f 1)" = NEW_BOOT_SHA
touch "$save/update-started"
apk --no-network add ./linux-oneplus-xigua-6.14-r1.apk ./device-oneplus-xigua-1-r4.apk ./device-oneplus-xigua-phosh-1-r4.apk ./firmware-oneplus-xigua-wifi-1-r0.apk
test "$(sha256sum /boot/vmlinuz | cut -d ' ' -f 1)" = KERNEL_SHA
override=/lib/modules/6.14.0-oneplus-xigua/updates/pja110-wifi/ath12k.ko
test "$(sha256sum "$override" | cut -d ' ' -f 1)" = 55b8200a0fd9dda6251799ab6e2d8a73c428060ca6c27c4720026e7da3efd31f
mv "$override" "$save/ath12k-override-before.ko"
depmod -a 6.14.0-oneplus-xigua
test "$(modinfo -F version ath12k)" = pja110-aston-rfkill-1
case "$(modinfo -F filename ath12k)" in */kernel/drivers/net/wireless/ath/ath12k/ath12k.ko) ;; *) exit 1;; esac
dd if=boot_a.img of="$a" bs=1048576 conv=fsync
test "$(sha256sum "$a" | cut -d ' ' -f 1)" = NEW_BOOT_SHA
sha256sum -c "$save/b-before.sha256"
touch "$save/update-complete"
sync
echo 'NATIVE_WIFI_APKS_AND_BOOT_A_VERIFIED; rebooting'
systemctl reboot
'''.replace('OLD_BOOT_SHA', sha(old)).replace('NEW_BOOT_SHA', sha(new)).replace('KERNEL_SHA', sha(kernel))
    (OUT / 'install.sh').write_bytes(script.encode())
    restore = '''#!/bin/sh
set -eu
test "$(id -u)" = 0
cd /home/penguin/wifi-bringup/native-test
save=/var/lib/pja110-wifi-native-test
test "$(sha256sum "$save/boot_a-before.img" | cut -d ' ' -f 1)" = OLD_BOOT_SHA
apk --no-network add ./rollback/linux-oneplus-xigua-6.14-r0.apk ./rollback/device-oneplus-xigua-1-r3.apk ./rollback/device-oneplus-xigua-phosh-1-r3.apk
override=/lib/modules/6.14.0-oneplus-xigua/updates/pja110-wifi/ath12k.ko
if [ -f "$save/ath12k-override-before.ko" ]; then
 install -Dm644 "$save/ath12k-override-before.ko" "$override"
fi
depmod -a 6.14.0-oneplus-xigua
dd if="$save/boot_a-before.img" of=/dev/disk/by-partlabel/boot_a bs=1048576 conv=fsync
sha256sum -c "$save/b-before.sha256"
sync
systemctl reboot
'''.replace('OLD_BOOT_SHA', sha(old))
    (OUT / 'restore.sh').write_bytes(restore.encode())
    files = sorted(OUT.glob('*.apk')) + [OUT / 'boot_a.img.gz', OUT / 'install.sh', OUT / 'restore.sh']
    files += sorted((OUT / 'rollback').glob('*.apk'))
    assert len(files) == 10
    manifest = {p.relative_to(OUT).as_posix(): sha(p.read_bytes()) for p in files}
    (OUT / 'files.sha256').write_bytes(''.join(f'{v}  {k}\n' for k, v in manifest.items()).encode())
    run('mkdir -p ' + REMOTE + '/rollback')
    for path in files + [OUT / 'files.sha256']:
        name = path.relative_to(OUT).as_posix()
        run('cat > ' + REMOTE + '/' + name, path.read_bytes())
        print('Staged:', name, flush=True)
    check = run(f'cd {REMOTE}; sha256sum -c files.sha256; sh -n install.sh; sh -n restore.sh; '
                'apk --no-network verify ./*.apk ./rollback/*.apk; '
                'apk --no-network add --simulate ./linux-oneplus-xigua-6.14-r1.apk ./device-oneplus-xigua-1-r4.apk ./device-oneplus-xigua-phosh-1-r4.apk ./firmware-oneplus-xigua-wifi-1-r0.apk')
    (OUT / 'phone-preflight.txt').write_bytes(check)
    print(check.decode(), flush=True)
    (OUT / 'manifest.json').write_text(json.dumps(dict(files=manifest,
        old_boot_sha256=sha(old), new_boot_sha256=sha(new), kernel_sha256=sha(kernel),
        root_uuid_preserved=True, staged=True, installed=False), indent=2) + '\n')


if __name__ == '__main__':
    main()
