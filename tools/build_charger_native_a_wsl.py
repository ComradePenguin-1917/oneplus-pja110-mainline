"""Isolated module build using the deployed A kernel config and overlay."""
from pathlib import Path
import hashlib, json, subprocess, tarfile, shutil
root = Path.home() / 'workspace/PJA110-Mainline'
win = Path('/mnt/h/workspace/PJA110-Mainline')
out = win / 'out/native-install-20261017/charger-init-candidate'
tree = root / 'charger-native-a/linux-6.14'
pkg = win / 'postmarketos/device/testing/linux-oneplus-xigua'
manifest = json.loads((pkg / 'source-manifest.json').read_text())
archive = root / '.cache/linux-6.14.tar.xz'
overlay = pkg / 'pja110-kernel-overlay.tar.gz'
assert hashlib.sha512(archive.read_bytes()).hexdigest() == manifest['base_sha512']
assert hashlib.sha512(overlay.read_bytes()).hexdigest() == manifest['overlay_sha512']
if not tree.exists():
    tree.parent.mkdir(exist_ok=True)
    print('Extracting cached source', flush=True)
    with tarfile.open(archive) as t:
        t.extractall(tree.parent)
    with tarfile.open(overlay) as t:
        t.extractall(tree)
shutil.copyfile(out / 'native-a.config', tree / '.config')
build = tree.parent / 'module'
build.mkdir(exist_ok=True)
for name in ('qcom_battmgr.c', 'pja110-ap-gauge.h', 'Makefile'):
    shutil.copyfile(win / 'drivers/power/supply' / name, build / name)
compiler = Path('/opt/aarch64-linux-gnu-toolchain-13.3/bin/aarch64-none-linux-gnu-gcc')
assert compiler.exists()
common = ['make', '-C', str(tree), 'ARCH=arm64', 'CROSS_COMPILE=' + str(compiler).removesuffix('gcc')]
with (out / 'native-a-build.log').open('wb') as log:
    for targets in (['olddefconfig'], ['-j8', 'modules_prepare'], ['M=' + str(build), 'KBUILD_MODPOST_WARN=1', 'modules']):
        print('Running ' + ' '.join(targets), flush=True)
        p = subprocess.run(common + targets, stdout=log, stderr=subprocess.STDOUT)
        log.flush()
        p.check_returncode()
release = (tree / 'include/config/kernel.release').read_text().strip()
assert release == '6.14.0-oneplus-xigua', release
module = build / 'qcom_battmgr.ko'
shutil.copyfile(module, out / module.name)
report = dict(module_link_passed=True, kernel_release=release, module_sha256=hashlib.sha256(module.read_bytes()).hexdigest(), compiler=str(compiler), modpost_missing_symvers=True, exported_symbols_verified=False, live_abi_verified=False, phone_installed=False, charging_enabled=False)
(out / 'native-a-build-result.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report, indent=2))
