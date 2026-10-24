"""Offline content checks for the two rebuilt baseline APKs.

Reads the APKs produced by ``run_pmbootstrap_isolated.sh baseline`` and asserts
the packaged pieces the running system used to get from ``/usr/local`` are
actually inside the packages, that module dependencies resolve, and that no
legacy path leaked into a package.
"""
import argparse
import hashlib
import io
import json
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(path):
    tf = tarfile.open(fileobj=io.BytesIO(path.read_bytes()), mode='r:gz')
    files = {}
    for member in tf.getmembers():
        if member.isfile():
            files[member.name] = {'data': tf.extractfile(member).read(),
                                  'mode': member.mode}
        elif member.issym():
            files[member.name] = {'link': member.linkname, 'mode': member.mode}
    return files


def pkg_info(files):
    text = files['.PKGINFO']['data'].decode()
    out = {}
    for line in text.splitlines():
        if ' = ' in line:
            k, v = line.split(' = ', 1)
            out.setdefault(k, []).append(v)
    return out


def version_key(path):
    import re
    m = re.search(r'-(\d+(?:\.\d+)*)-r(\d+)\.apk$', path.name)
    assert m, path.name
    return tuple(int(x) for x in m.group(1).split('.')) + (int(m.group(2)),)


def find_one(directory, prefix):
    matches = sorted(directory.glob(prefix + '-*.apk'), key=version_key)
    assert matches, f'no {prefix} APK in {directory}'
    return matches[-1]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--apk-dir', default='out/baseline-20261017')
    ap.add_argument('--out', default='out/baseline-20261017/apk-verification.json')
    args = ap.parse_args()
    directory = ROOT / args.apk_dir
    kernel_apk = find_one(directory, 'linux-oneplus-xigua')
    device_apk = find_one(directory, 'device-oneplus-xigua')

    result = {'apks': {}, 'checks': {}, 'passed': False}
    for label, path in (('kernel', kernel_apk), ('device', device_apk)):
        files = load(path)
        info = pkg_info(files)
        version = info.get('pkgver', ['?'])[0]
        if '-r' not in version:
            version += '-r' + info.get('pkgrel', ['?'])[0]
        result['apks'][label] = {
            'file': path.name,
            'bytes': path.stat().st_size,
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'version': version,
            'files': len([k for k, v in files.items() if 'data' in v]),
        }
        if label == 'kernel':
            release = files['usr/share/kernel/oneplus-xigua/kernel.release']['data'].decode().strip()
            deps = files[f'usr/lib/modules/{release}/modules.dep']['data'].decode()
            modules = {
                'qcom_battmgr': f'kernel/drivers/power/supply/qcom_battmgr.ko',
                'qcom_spmi_adc5_gen3': f'kernel/drivers/iio/adc/qcom-spmi-adc5-gen3.ko',
                'qcom_vadc_common': f'kernel/drivers/iio/adc/qcom-vadc-common.ko',
                'synaptics_aston': 'extra/synaptics-aston.ko',
            }
            for module, rel in modules.items():
                key = f'usr/lib/modules/{release}/{rel}'
                assert key in files, f'kernel APK lacks {key}'
                assert rel in deps or rel.replace('.ko', '') in deps, f'{rel} missing from modules.dep'
            battmgr = files[f'usr/lib/modules/{release}/kernel/drivers/power/supply/qcom_battmgr.ko']['data']
            assert b'pja110-single-battery-1' in battmgr, 'battmgr module version missing'
            assert b'oneplus,xigua' in battmgr, 'single-battery quirk missing'
            assert b'pja110_charger_init' not in battmgr, 'experimental charger path shipped'
            adc = files[f'usr/lib/modules/{release}/kernel/drivers/iio/adc/qcom-spmi-adc5-gen3.ko']['data']
            assert b'spmi-adc5-gen3' in adc
            assert 'boot/vmlinuz' in files
            result['checks']['kernel'] = {
                'release': release,
                'modules_in_dep': list(modules),
                'battmgr_version': 'pja110-single-battery-1',
                'single_battery_quirk': True,
                'charger_init_path_absent': True,
                'adc_driver_in_tree': True,
            }
        else:
            unit = 'usr/lib/systemd/system/pja110-boot-success.service'
            wants = 'etc/systemd/system/graphical.target.wants/pja110-boot-success.service'
            for key in (unit, 'usr/libexec/pja110-mark-a-success',
                        'usr/libexec/pja110-migrate-baseline',
                        'usr/share/device-oneplus-xigua/verified-vendor.dtb',
                        'usr/lib/modules-load.d/00-device-oneplus-xigua.conf',
                        'usr/lib/systemd/system-preset/80-pja110-baseline.preset'):
                assert key in files, f'device APK lacks {key}'
            preset = files['usr/lib/systemd/system-preset/80-pja110-baseline.preset']['data'].decode()
            assert 'enable pja110-boot-success.service' in preset, 'preset does not enable the unit'
            assert files['usr/libexec/pja110-mark-a-success']['mode'] & 0o111
            assert files['usr/libexec/pja110-migrate-baseline']['mode'] & 0o111
            assert wants in files and files[wants].get('link') == \
                '/usr/lib/systemd/system/pja110-boot-success.service', 'enablement symlink wrong'
            modules_load = files['usr/lib/modules-load.d/00-device-oneplus-xigua.conf']['data'].decode()
            assert 'qcom_battmgr' in modules_load and 'qcom-spmi-adc5-gen3' in modules_load
            info = pkg_info(files)
            assert any('qbootctl' in dep for dep in info.get('depend', [])), 'qbootctl dependency missing'
            dtb = files['usr/share/device-oneplus-xigua/verified-vendor.dtb']['data']
            repo_dtb = (ROOT / 'postmarketos/device/testing/device-oneplus-xigua/verified-vendor.dtb').read_bytes()
            assert dtb == repo_dtb, 'packaged DTB differs from the authoritative source'
            assert not any(name.startswith(('usr/local', 'home/')) for name in files), \
                'legacy /usr/local or home path shipped'
            result['checks']['device'] = {
                'boot_success_unit': True,
                'mark_script_executable': True,
                'migration_script_executable': True,
                'package_owned_enablement_symlink': True,
                'systemd_preset_enables_unit': True,
                'modules_load_entries': True,
                'qbootctl_dependency': True,
                'verified_vendor_dtb_matches_source': True,
                'legacy_paths_absent': True,
            }
    result['passed'] = True
    out = ROOT / args.out
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n')
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
