"""Build existing ath12k with Aston's WCN7850 no-hardware-switch parameters."""
from pathlib import Path
import difflib
import hashlib
import json
import shutil
import subprocess

win = Path('/mnt/h/workspace/PJA110-Mainline')
base = Path.home() / 'workspace/PJA110-Mainline/charger-native-a'
kernel = base / 'linux-6.14'
source = kernel / 'drivers/net/wireless/ath/ath12k'
build = base / 'wifi-aston-rfkill/ath12k'
out = win / 'out/wifi-bringup-20261017/aston-rfkill'
build.mkdir(parents=True, exist_ok=True)
out.mkdir(exist_ok=True)
for p in source.iterdir():
    if p.suffix in ['.c', '.h'] or p.name == 'Makefile':
        shutil.copyfile(p, build / p.name)
# Preserve relative references, if this driver revision uses any ath parent headers.
for p in source.parent.glob('*.h'):
    shutil.copyfile(p, build.parent / p.name)
original = (source / 'hw.c').read_text()
start = original.index('.hw_rev = ATH12K_HW_WCN7850_HW20')
end = original.index('\n\t{', start)
block = original[start:end]
assert block.count('.rfkill_pin = 48,') == 1
assert block.count('.rfkill_on_level = 1,') == 1
changed = block.replace('.rfkill_pin = 48,', '.rfkill_pin = 0,').replace('.rfkill_on_level = 1,', '.rfkill_on_level = 0,')
aston = (win / 'out/wifi-bringup-20261017/aston-ath12k-hw.c').read_text()
astart = aston.index('.hw_rev = ATH12K_HW_WCN7850_HW20')
aend = aston.index('\n\t{', astart)
assert changed == aston[astart:aend], 'Aston hardware block differs beyond selected RF-kill fields'
edited = original[:start] + changed + original[end:]
(build / 'hw.c').write_text(edited)
core = (build / 'core.c').read_text()
assert 'MODULE_VERSION(' not in core
(build / 'core.c').write_text(core + '\nMODULE_VERSION("pja110-aston-rfkill-1");\n')
patch = ''.join(difflib.unified_diff(original.splitlines(True), edited.splitlines(True),
                                   fromfile='a/drivers/net/wireless/ath/ath12k/hw.c',
                                   tofile='b/drivers/net/wireless/ath/ath12k/hw.c'))
(out / 'aston-rfkill.patch').write_text(patch)
print(patch, flush=True)
assert (kernel / 'include/config/kernel.release').read_text().strip() == '6.14.0-oneplus-xigua'
# The charger build tree has the vmlinux symbols but not all networking module
# exports. Build those normal dependencies and pass their real symbol tables;
# do not suppress modpost errors or fabricate exports.
extras = []
arc4 = build.parent / 'libarc4'
arc4.mkdir(exist_ok=True)
shutil.copyfile(kernel / 'lib/crypto/arc4.c', arc4 / 'arc4.c')
(arc4 / 'Makefile').write_text('obj-m += libarc4.o\nlibarc4-y := arc4.o\n')
for relative in ['net/rfkill', 'libarc4', 'net/wireless', 'net/mac80211', 'drivers/bus/mhi/host']:
    dependency = arc4 if relative == 'libarc4' else kernel / relative
    dep_cmd = ['make', '-C', str(kernel), 'ARCH=arm64',
               'CROSS_COMPILE=/opt/aarch64-linux-gnu-toolchain-13.3/bin/aarch64-none-linux-gnu-',
               'M=' + str(dependency), '-j4', 'modules']
    if extras:
        dep_cmd.append('KBUILD_EXTRA_SYMBOLS=' + ' '.join(extras))
    print('Building module dependency:', relative, flush=True)
    log_path = out / ('dependency-' + relative.replace('/', '-') + '.log')
    with log_path.open('w') as log:
        p = subprocess.run(dep_cmd, stdout=log, stderr=subprocess.STDOUT)
    if p.returncode:
        print(log_path.read_text()[-4000:], flush=True)
        p.check_returncode()
    extras.append(str(dependency / 'Module.symvers'))
cmd = ['make', '-C', str(kernel), 'ARCH=arm64',
       'CROSS_COMPILE=/opt/aarch64-linux-gnu-toolchain-13.3/bin/aarch64-none-linux-gnu-',
       'M=' + str(build), '-j4', 'modules', 'KBUILD_EXTRA_SYMBOLS=' + ' '.join(extras)]
with (out / 'build.log').open('w') as log:
    p = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT)
print((out / 'build.log').read_text()[-3000:])
p.check_returncode()
module = (build / 'ath12k.ko').read_bytes()
(out / 'ath12k.ko').write_bytes(module)
info = subprocess.run(['modinfo', str(build / 'ath12k.ko')], check=True, capture_output=True, text=True).stdout
(out / 'modinfo.txt').write_text(info)
print(info)
report = dict(sha256=hashlib.sha256(module).hexdigest(), version='pja110-aston-rfkill-1',
              source_hw_sha256=hashlib.sha256(original.encode()).hexdigest(),
              reference='jiganomegsdfdf/aston-mainline@5d5c840896bb49291ae4578acefd5a3ec65524f6',
              scope='WCN7850 hw2 rfkill_pin 48->0 and rfkill_on_level 1->0; module version metadata',
              wcn7850_hw_block_matches_aston=True, phone_tested=False)
(out / 'manifest.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report, indent=2))
