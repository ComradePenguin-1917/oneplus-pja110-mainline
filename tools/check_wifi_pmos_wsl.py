"""Exercise Wi-Fi package staging and patch application without sudo."""
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from fdt import FDT

ROOT = Path('/mnt/h/workspace/PJA110-Mainline')
CHECKOUT = Path.home() / 'workspace/PJA110-Mainline/pmaports'
BASE = CHECKOUT / 'device/testing'
SOURCE = Path.home() / 'workspace/PJA110-Mainline/charger-native-a/linux-6.14'
OUT = ROOT / 'out/wifi-bringup-20261017/package-integration'
OUT.mkdir(exist_ok=True)


def run(args, **kwargs):
    return subprocess.run(args, check=True, capture_output=True, text=True, **kwargs).stdout


for name in ['firmware-oneplus-xigua-wifi', 'linux-oneplus-xigua', 'device-oneplus-xigua']:
    directory = BASE / name
    recipe = directory / 'APKBUILD'
    assert b'\r' not in recipe.read_bytes(), recipe
    run(['bash', '-n', str(recipe)])
    for expected, name in re.findall(r'([0-9a-f]{128})  ([^\s]+)', recipe.read_text()):
        path = directory / name
        if path.is_file():
            assert hashlib.sha512(path.read_bytes()).hexdigest() == expected, path

with tempfile.TemporaryDirectory(prefix='pja110-wifi-package-') as work:
    work = Path(work)
    tree = work / 'kernel'
    driver = tree / 'drivers/net/wireless/ath/ath12k'
    driver.mkdir(parents=True)
    for name in ['hw.c', 'core.c']:
        shutil.copyfile(SOURCE / driver.relative_to(tree) / name, driver / name)
    patch = BASE / 'linux-oneplus-xigua/aston-wcn7850-rfkill.patch'
    output = run(['patch', '--batch', '--fuzz=0', '-p1', '-i', str(patch)], cwd=tree)
    print(output)
    assert 'offset' not in output, output
    # Match the exact source files used to build the phone-tested override.
    tested = SOURCE.parent / 'wifi-aston-rfkill/ath12k'
    for name in ['hw.c', 'core.c']:
        assert (driver / name).read_bytes() == (tested / name).read_bytes(), name
    firmware = BASE / 'firmware-oneplus-xigua-wifi'
    staging = work / 'package'
    run(['bash', '-ec', 'startdir=$1; srcdir=$1; pkgdir=$2; . "$1/APKBUILD"; package',
         'stage', str(firmware), str(staging)])
    for name in ['amss.bin', 'm3.bin', 'board.bin', 'regdb.bin']:
        installed = staging / 'usr/lib/firmware/ath12k/WCN7850/hw2.0' / name
        assert installed.read_bytes() == (firmware / name).read_bytes(), name

device = BASE / 'device-oneplus-xigua'
dtb = (device / 'verified-vendor.dtb').read_bytes()
assert dtb == (ROOT / 'out/wifi-bringup-20261017/wifi-added.dtb').read_bytes()
tree = FDT(dtb).nodes()
assert tree['/wcn7850-pmu']['compatible'] == b'qcom,wcn7850-pmu\0'
config = (BASE / 'linux-oneplus-xigua/config-oneplus-xigua.aarch64').read_text()
for setting in ['ATH12K', 'POWER_SEQUENCING', 'POWER_SEQUENCING_QCOM_WCN',
                'PCI_PWRCTL_PWRSEQ', 'QRTR_MHI']:
    assert f'CONFIG_{setting}=m\n' in config, setting
profile = json.loads((ROOT / 'postmarketos/integration-profile.json').read_text())
assert profile['packages']['linux-oneplus-xigua'] == '6.14-r1'
assert profile['packages']['device-oneplus-xigua'] == '1-r4'
assert profile['packages']['firmware-oneplus-xigua-wifi'] == '1-r0'
result = dict(syntax_and_local_checksums_passed=True,
              kernel_patch_matches_phone_tested_sources=True,
              firmware_package_staging_passed=True,
              device_tree_matches_phone_tested_artifact=True,
              power_sequencing_configuration_passed=True,
              apk_built=False, new_image_built=False, phone_modified=False)
(OUT / 'preflight.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result, indent=2))
