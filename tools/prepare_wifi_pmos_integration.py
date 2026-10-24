"""Package the phone-tested Wi-Fi artifacts without touching the phone."""
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'postmarketos/device/testing'
WIFI = ROOT / 'out/wifi-bringup-20261017'


def write(path, text):
    path.write_bytes(text.replace('\r\n', '\n').encode())


def checksums(directory, text):
    def replace(match):
        name = match[2]
        path = directory / name
        return (hashlib.sha512(path.read_bytes()).hexdigest() + '  ' + name
                if path.is_file() else match[0])
    return re.sub(r'([0-9a-f]{128})  ([^\s]+)', replace, text)


def main():
    firmware = BASE / 'firmware-oneplus-xigua-wifi'
    firmware.mkdir(exist_ok=True)
    mappings = {
        'amss.bin': ('amss20.bin', 'e6d7816a71eebb147dade9e928c9e1c7a9a79399d770226aae85b4ca83b692d6'),
        'm3.bin': ('phy_ucode20.elf', '2a22bf383890ee2ece5e1b9598b24173a4e7f5d710f441bb3963f575c9729ce0'),
        'board.bin': ('bdwlan.elf', '39de9b864cd5054a8f5b60a415052b244aa50ccde0104da3f8f9ab0c6a4021bb'),
        'regdb.bin': ('regdb.bin', 'a37849f717efd5974f88adf9f061f72387e5cff79eba867d12f404e09276ab9f'),
    }
    for dest, (name, expected) in mappings.items():
        data = (WIFI / 'stock-kiwi' / name).read_bytes()
        if hashlib.sha256(data).hexdigest() != expected:
            raise RuntimeError('Wrong phone-tested firmware: ' + name)
        (firmware / dest).write_bytes(data)
    recipe = '''# Local OEM firmware extracted from this PJA110; no redistribution grant.
maintainer="PJA110 Mainline project <pja110@local.invalid>"
pkgname=firmware-oneplus-xigua-wifi
pkgver=1
pkgrel=0
pkgdesc="PJA110 WCN7850 hw2.0 matching OEM WLAN firmware and board data"
url="https://postmarketos.org"
arch="aarch64"
license="LicenseRef-proprietary"
options="!check !strip"
source="amss.bin m3.bin board.bin regdb.bin"

package() {
    for f in amss.bin m3.bin board.bin regdb.bin; do
        install -Dm644 "$srcdir/$f" "$pkgdir/usr/lib/firmware/ath12k/WCN7850/hw2.0/$f"
    done
}

sha512sums="
'''
    for name in mappings:
        recipe += hashlib.sha512((firmware / name).read_bytes()).hexdigest() + '  ' + name + '\n'
    write(firmware / 'APKBUILD', recipe + '"\n')
    provenance = dict(source='local PJA110 701 payload modem image, image/kiwi',
                      oem_reference='OnePlusOSS/android_kernel_modules_and_devicetree_oneplus_sm8550@f034653c086942be9398171cfa7477ddbe2d9504',
                      files={k: dict(source=v[0], sha256=v[1]) for k, v in mappings.items()},
                      wireless_test='out/wifi-bringup-20261017/wireless-ssh-20261017-161606.json')
    write(firmware / 'source-manifest.json', json.dumps(provenance, indent=2) + '\n')

    kernel = BASE / 'linux-oneplus-xigua'
    patch = (WIFI / 'aston-rfkill/aston-rfkill.patch').read_text()
    patch += '''--- a/drivers/net/wireless/ath/ath12k/core.c
+++ b/drivers/net/wireless/ath/ath12k/core.c
@@ -1951,2 +1951,4 @@
 MODULE_DESCRIPTION("Core module for Qualcomm Atheros 802.11be wireless LAN cards.");
 MODULE_LICENSE("Dual BSD/GPL");
+
+MODULE_VERSION("pja110-aston-rfkill-1");
'''
    write(kernel / 'aston-wcn7850-rfkill.patch', patch)
    text = (kernel / 'APKBUILD').read_text()
    text = re.sub(r'^pkgrel=\d+$', 'pkgrel=1', text, flags=re.M)
    if '\taston-wcn7850-rfkill.patch\n' not in text:
        text = text.replace('\tconfig-oneplus-xigua.aarch64\n',
                            '\tconfig-oneplus-xigua.aarch64\n\taston-wcn7850-rfkill.patch\n')
        text = text.rstrip().removesuffix('"') + hashlib.sha512((kernel / 'aston-wcn7850-rfkill.patch').read_bytes()).hexdigest() + '  aston-wcn7850-rfkill.patch\n"\n'
    write(kernel / 'APKBUILD', checksums(kernel, text))
    manifest_path = kernel / 'source-manifest.json'
    manifest = json.loads(manifest_path.read_text())
    manifest['patches'] = [{'path': 'aston-wcn7850-rfkill.patch',
                            'sha256': hashlib.sha256((kernel / 'aston-wcn7850-rfkill.patch').read_bytes()).hexdigest(),
                            'reference': 'jiganomegsdfdf/aston-mainline@5d5c840896bb49291ae4578acefd5a3ec65524f6',
                            'phone_tested_source_match': True}]
    write(manifest_path, json.dumps(manifest, indent=2) + '\n')

    device = BASE / 'device-oneplus-xigua'
    dtb = (WIFI / 'wifi-added.dtb').read_bytes()
    (device / 'verified-vendor.dtb').write_bytes(dtb)
    text = (device / 'APKBUILD').read_text()
    text = re.sub(r'^pkgrel=\d+$', 'pkgrel=4', text, flags=re.M)
    if ' firmware-oneplus-xigua-wifi' not in text:
        text = text.replace('firmware-oneplus-xigua-adsp"', 'firmware-oneplus-xigua-adsp firmware-oneplus-xigua-wifi"')
    text = text.replace('ABL currently consumes it through vendor_boot_b.',
                        'ABL consumes the verified Wi-Fi/ADC tree through vendor_boot_a.')
    write(device / 'APKBUILD', checksums(device, text))
    profile_path = ROOT / 'postmarketos/integration-profile.json'
    profile = json.loads(profile_path.read_text())
    profile['packages'].update({'device-oneplus-xigua': '1-r4', 'device-oneplus-xigua-phosh': '1-r4',
                                'linux-oneplus-xigua': '6.14-r1', 'firmware-oneplus-xigua-wifi': '1-r0'})
    profile['hardware_baseline']['wifi'] = 'WCN7850 OEM hw2 firmware, Aston RF-kill parameters and power topology; wireless SSH verified'
    profile['rootfs_built_and_verified'] = False
    profile['phone_native_boot_verified'] = False
    write(profile_path, json.dumps(profile, indent=2) + '\n')
    print('Prepared Wi-Fi firmware 1-r0, kernel 6.14-r1 and device 1-r4; no phone changes')


if __name__ == '__main__':
    main()
