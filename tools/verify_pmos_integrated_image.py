"""Inspect the exported rootfs without mounting it or requiring root."""
from pathlib import Path
import argparse
import hashlib
import json
import shutil
import subprocess
import tempfile
from pmos_image_info import inspect_image

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--export', default='/tmp/postmarketOS-export')
parser.add_argument('--out-dir', default='out/postmarketos-baseline-20261017')
options = parser.parse_args()

win = Path('/mnt/h/workspace/PJA110-Mainline')
export = Path(options.export)
out = win / options.out_dir
out.mkdir(parents=True, exist_ok=True)
profile = json.loads((win / 'postmarketos/integration-profile.json').read_text())
image = export / 'oneplus-xigua.img'
info = inspect_image(image)
partition = next(p for p in info['partitions'] if p['label'] == 'pmOS_root')
boot_partition = next(p for p in info['partitions'] if p['label'] == 'pmOS_boot')
length = partition['sectors'] * info['sector_size']
assert shutil.disk_usage(tempfile.gettempdir()).free > length + boot_partition['sectors']*info['sector_size'] + 256*1024*1024, 'Insufficient inspection scratch space'
assert shutil.which('debugfs'), 'debugfs is required for read-only ext4 inspection'
with tempfile.TemporaryDirectory(prefix='pmos-image-verify-') as work:
    work = Path(work)
    root_image = work / 'root.ext4'
    remaining = length
    digest = hashlib.sha256()
    with image.open('rb') as source, root_image.open('wb') as target:
        source.seek(partition['start'] * info['sector_size'])
        while remaining:
            block = source.read(min(4*1024*1024, remaining))
            assert block, 'Truncated root partition'
            target.write(block)
            digest.update(block)
            remaining -= len(block)

    boot_image = work / 'boot.ext4'
    boot_digest = hashlib.sha256()
    with image.open('rb') as source, boot_image.open('wb') as target:
        source.seek(boot_partition['start'] * info['sector_size'])
        remaining = boot_partition['sectors'] * info['sector_size']
        while remaining:
            block = source.read(min(4*1024*1024, remaining))
            assert block, 'Truncated boot partition'
            target.write(block)
            boot_digest.update(block)
            remaining -= len(block)

    def read_file(path, filesystem=root_image):
        # debugfs can return zero for a missing file; require an actual dump.
        target = work / 'dump'
        target.unlink(missing_ok=True)
        p = subprocess.run(['debugfs', '-R', f'dump {path} {target}', str(filesystem)],
                           capture_output=True)
        assert p.returncode == 0 and target.exists(), (path, p.stderr.decode(errors='replace'))
        return target.read_bytes()

    installed = {}
    for block in read_file('/usr/lib/apk/db/installed').decode().split('\n\n'):
        fields = dict(line.split(':', 1) for line in block.splitlines() if ':' in line)
        if 'P' in fields:
            installed[fields['P']] = fields.get('V')
    for name, version in profile['packages'].items():
        assert installed.get(name) == version, (name, installed.get(name), version)
    (out / 'resolved-packages.json').write_text(json.dumps(installed, indent=2, sort_keys=True) + '\n')
    device = win / 'postmarketos/device/testing/device-oneplus-xigua'
    for source, destination in {
        'phoc.ini': '/usr/share/phosh/phoc.ini',
        'modules-load.conf': '/usr/lib/modules-load.d/00-device-oneplus-xigua.conf',
        'modprobe.conf': '/usr/lib/modprobe.d/device-oneplus-xigua.conf',
        'deviceinfo': '/usr/share/deviceinfo/device-oneplus-xigua',
        'verified-vendor.dtb': '/usr/share/device-oneplus-xigua/verified-vendor.dtb',
        'kernel-cmdline.conf': '/usr/lib/kernel-cmdline.d/50-device-oneplus-xigua.conf',
    }.items():
        expected_source = (device / source).read_bytes()
        if source == 'deviceinfo' or Path(source).suffix in {'.conf', '.ini'}:
            # prepare_pmos_integrated_build normalizes package text to LF.
            # Require those exact installed bytes; DTBs remain byte-exact.
            expected_source = expected_source.replace(b'\r\n', b'\n')
        assert read_file(destination) == expected_source, destination
    firmware = win / 'postmarketos/device/testing/firmware-oneplus-xigua-adreno'
    for source, destination in {
        'a740_sqe.fw': '/usr/lib/firmware/qcom/a740_sqe.fw',
        'gmu_gen70200.bin': '/usr/lib/firmware/qcom/gmu_gen70200.bin',
        'a740_zap.mbn': '/usr/lib/firmware/qcom/sm8550/xigua/a740_zap.mbn',
    }.items():
        assert read_file(destination) == (firmware / source).read_bytes(), destination
    wifi = win / 'postmarketos/device/testing/firmware-oneplus-xigua-wifi'
    for name in ['amss.bin', 'm3.bin', 'board.bin', 'regdb.bin']:
        destination = '/usr/lib/firmware/ath12k/WCN7850/hw2.0/' + name
        assert read_file(destination) == (wifi / name).read_bytes(), destination
    reference = json.loads((win / 'out/phoc-atomic-fix-20261016/apk-aarch64/verification.json').read_text())
    expected = next(r['binary_sha256'] for r in reference if r['metadata']['pkgname'] == ['phoc'])
    assert hashlib.sha256(read_file('/usr/bin/phoc')).hexdigest() == expected, 'Different Phoc binary from phone-tested APK'
    release = read_file('/usr/share/kernel/oneplus-xigua/kernel.release').decode().strip()
    assert read_file(f'/usr/lib/modules/{release}/extra/synaptics-aston.ko'), 'Touch module missing'

    # Recovered baseline pieces must be served by packages, not by /usr/local.
    for path in ['/usr/lib/systemd/system/pja110-boot-success.service',
                 '/usr/libexec/pja110-mark-a-success',
                 '/usr/libexec/pja110-migrate-baseline',
                 '/usr/bin/qbootctl',
                 '/usr/share/doc/device-oneplus-xigua/baseline.md']:
        assert read_file(path), f'missing packaged baseline file {path}'
    modules_dep = read_file(f'/usr/lib/modules/{release}/modules.dep').decode()
    module_paths = {
        'qcom_battmgr': f'/usr/lib/modules/{release}/kernel/drivers/power/supply/qcom_battmgr.ko',
        'adc5': f'/usr/lib/modules/{release}/kernel/drivers/iio/adc/qcom-spmi-adc5-gen3.ko',
        'vadc': f'/usr/lib/modules/{release}/kernel/drivers/iio/adc/qcom-vadc-common.ko',
    }
    for label, path in module_paths.items():
        rel = path.split(f'/usr/lib/modules/{release}/', 1)[1]
        assert rel in modules_dep, f'{label} missing from modules.dep ({rel})'
        dumped = work / (label + '.ko')
        dump = subprocess.run(['debugfs', '-R', f'dump {path} {dumped}', str(root_image)],
                              capture_output=True)
        assert dump.returncode == 0 and dumped.exists() and dumped.stat().st_size > 0, path
    battmgr = work / 'qcom_battmgr.ko'
    battmgr_version = subprocess.run(['modinfo', '-F', 'version', str(battmgr)],
                                     capture_output=True, text=True).stdout.strip()
    assert battmgr_version == 'pja110-single-battery-1', battmgr_version
    assert subprocess.run(['modinfo', '-F', 'name', str(work / 'adc5.ko')],
                          capture_output=True, text=True).stdout.strip() == 'qcom_spmi_adc5_gen3'
    # The temporary bring-up units must not exist at all in the image.
    for legacy in ['/etc/systemd/system/pja110-adc-test.service',
                   '/etc/systemd/system/pja110-battmgr-readonly.service',
                   '/etc/systemd/system/pja110-charger-capture.service',
                   '/etc/systemd/system/pja110-wifi-probe.service',
                   '/usr/local/lib/pja110/qcom_battmgr.ko']:
        probe = subprocess.run(['debugfs', '-R', f'stat {legacy}', str(root_image)],
                               capture_output=True, text=True)
        assert 'Inode:' not in probe.stdout, f'legacy artifact packaged: {legacy}'
    # /boot is a separate filesystem: its root contains vmlinuz and initramfs.
    assert read_file('/vmlinuz', boot_image) == (export / 'vmlinuz').read_bytes()
    assert read_file('/initramfs', boot_image), 'Boot partition initramfs missing'
    fstab = read_file('/etc/fstab').decode()
    assert f"UUID={partition['uuid']} / " in fstab
    assert f"UUID={boot_partition['uuid']} /boot " in fstab
    assert (export / 'initramfs').stat().st_size > 0
    result = {'image': info, 'root_partition_sha256': digest.hexdigest(),
              'boot_partition_sha256': boot_digest.hexdigest(), 'fstab_uuids_verified': True,
              'local_packages': profile['packages'], 'kernel_release': release,
              'phone_tested_phoc_sha256': expected, 'configuration_firmware_and_touch_module_passed': True,
              'packaged_baseline_pieces': {
                  'boot_success_unit': True, 'boot_success_script': True,
                  'migration_script': True, 'qbootctl': True,
                  'qcom_battmgr_version': battmgr_version,
                  'qcom_spmi_adc5_gen3_in_modules_dep': True,
                  'legacy_usr_local_absent': True,
              },
              'image_contents_verified': True, 'phone_partitions_written': False,
              'native_phone_boot_tested': False}
    (out / 'image-verification.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))
    print('PASS: exported image contains the reviewed package baseline; native boot still pending')
