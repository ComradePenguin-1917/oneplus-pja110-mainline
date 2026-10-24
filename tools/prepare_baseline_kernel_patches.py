"""Regenerate the maintained kernel-package patches for PJA110.

Inputs are pinned and hash-checked:

  * ``drivers/power/supply/qcom_battmgr.c`` from Linux v6.14 (upstream),
  * ``drivers/iio/adc/qcom-spmi-adc5-gen3.c`` and
    ``include/linux/iio/adc/qcom-adc5-gen3-common.h`` from upstream commit
    3857c2fe5449541e24afc5efdb0f81a8a8f9a3a0.

Outputs land in ``postmarketos/device/testing/linux-oneplus-xigua``:

  * ``qcom-battmgr-single-battery.patch``  -- PJA110 single-battery quirk only,
  * ``qcom-spmi-adc5-gen3-6.14.patch``     -- Kconfig/Makefile integration,
  * ``qcom-spmi-adc5-gen3.c``              -- verbatim upstream + one-line compat,
  * ``qcom-adc5-gen3-common.h``            -- verbatim upstream header.

No phone access, no compiled artifacts, no experimental charger paths.
"""
import argparse
import difflib
import hashlib
import json
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / 'postmarketos/device/testing/linux-oneplus-xigua'
STAGE = ROOT / 'out/baseline-20261017/raw'
DEFAULT_STAGE = ROOT / 'out/baseline-20261017/raw'

BATTMGR_V614_SHA256 = '483cf64c268cbe4ea551084bc066b8e68cf4ddaf4212c77a0a281272c7f07714'
ADC_SHA256 = '572de16ee968e8b0b716864d37b0c2f387af45ff66a3f5a895ecfc451fb8c615'
ADC_HDR_SHA256 = 'd5ff2284bb2dacb05c7d58e14a3814c901e6151f4a64740a184ad70ea2356d3a'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def read_text_lf(path):
    """Read text without newline translation; package sources must stay LF."""
    return path.read_bytes().decode('utf-8')


def write_text_lf(path, text):
    """Write UTF-8 text with LF endings regardless of host platform."""
    assert '\r\n' not in text, path
    path.write_bytes(text.encode('utf-8'))


def unified(old, new, fromfile, tofile):
    return ''.join(difflib.unified_diff(old.splitlines(True), new.splitlines(True),
                                        fromfile=fromfile, tofile=tofile))


def strip_charger_init(source):
    """Remove the opt-in charger/AP-gauge path from the verified bring-up source.

    The verified module ran with ``pja110_charger_init=0``, so this code never
    executed.  It is not shipped at all: the packaging task must not carry an
    unvalidated charging-control path, not even behind a module parameter.
    """
    s = source
    param = ('static bool pja110_charger_init;\n'
             'module_param(pja110_charger_init, bool, 0400);\n'
             'MODULE_PARM_DESC(pja110_charger_init, '
             '"Opt in to PJA110 OEM 500mA charger initialization");\n'
             '#define BATT_CHG_EN 24\n\n')
    assert s.count(param) == 1
    s = s.replace(param, '')

    start = s.index('/* Gated downstream initialization adapted from oplus_chg_hw_init. */')
    end = s.index('static void qcom_battmgr_enable_worker', start)
    s = s[:start] + s[end:]
    s = s.replace('#include "pja110-ap-gauge.h"\n\n', '')

    old = '''\tmutex_lock(&battmgr->lock);
\tret = qcom_battmgr_request(battmgr, &req, sizeof(req));
\tif (!ret)
\t\tret = qcom_battmgr_pja110_init(battmgr);
\tmutex_unlock(&battmgr->lock);
\tif (ret)
\t\tdev_err(battmgr->dev, "notification/charger initialization stopped: %d\\n", ret);'''
    new = '''\tret = qcom_battmgr_request(battmgr, &req, sizeof(req));
\tif (ret)
\t\tdev_err(battmgr->dev, "failed to request power notifications\\n");'''
    assert s.count(old) == 1
    s = s.replace(old, new)
    for banned in ('pja110_charger_init', 'pja110_ap_gauge', 'BATT_CHG_EN',
                   'pja110-ap-gauge.h'):
        assert banned not in s, banned
    # The verified telemetry guards must survive.
    for kept in ('request_failed', 'pending_set_opcode', 'cancel_work_sync'):
        assert kept in s, kept
    return s


def single_battery(source):
    """Apply only the verified PJA110 single-battery behaviour."""
    s = source
    old = '\t\tpower_supply_changed(battmgr->bat_psy);'
    assert s.count(old) == 1
    s = s.replace(old, '\t\tif (battmgr->bat_psy)\n'
                       '\t\t\tpower_supply_changed(battmgr->bat_psy);')

    start = s.index('static int qcom_battmgr_probe(')
    head, probe = s[:start], s[start:]
    decl = '\tstruct device *dev = &adev->dev;\n'
    assert probe.count(decl) == 1
    probe = probe.replace(decl, decl +
                          '\tstruct device_node *gauge;\n'
                          '\tbool external_gauge = false;\n', 1)
    needle = '\tif (battmgr->variant == QCOM_BATTMGR_SC8280XP) {'
    assert probe.count(needle) == 1
    probe = probe.replace(needle, '''\t/* PJA110 exposes its AP-owned pack gauge separately. ADSP reports
\t * placeholder battery values, but still supplies useful USB telemetry.
\t */
\tif (of_machine_is_compatible("oneplus,xigua")) {
\t\tgauge = of_find_compatible_node(NULL, NULL, "ti,bq28z610");
\t\tif (gauge) {
\t\t\texternal_gauge = of_device_is_available(gauge);
\t\t\tof_node_put(gauge);
\t\t}
\t}

''' + needle)

    block = '''\t\tbattmgr->bat_psy = devm_power_supply_register(dev, &sm8350_bat_psy_desc, &psy_cfg);
\t\tif (IS_ERR(battmgr->bat_psy))
\t\t\treturn dev_err_probe(dev, PTR_ERR(battmgr->bat_psy),
\t\t\t\t\t     "failed to register battery power supply\\n");'''
    assert probe.count(block) == 1
    probe = probe.replace(block, '\t\tif (!external_gauge) {\n' +
                          '\n'.join('\t' + line for line in block.splitlines()) +
                          '\n\t\t} else {\n'
                          '\t\t\tdev_info(dev, "using external BQ28Z610 battery telemetry\\n");\n'
                          '\t\t}')
    s = head + probe
    assert 'MODULE_VERSION(' not in s
    s = s.rstrip('\n') + '\n\nMODULE_VERSION("pja110-single-battery-1");\n'
    return s


def adc_compat(source):
    """The only change needed for 6.14: devres.h split landed after 6.14."""
    assert '#include <linux/device/devres.h>\n' in source
    return source.replace('#include <linux/device/devres.h>\n', '')


def add_kconfig(base):
    """Insert the pinned upstream Kconfig block just before the VADC entry."""
    block = '''config QCOM_SPMI_ADC5_GEN3
\ttristate "Qualcomm SPMI PMIC5 GEN3 ADC"
\tdepends on SPMI && THERMAL
\tselect REGMAP_SPMI
\tselect QCOM_VADC_COMMON
\tselect AUXILIARY_BUS
\thelp
\t  IIO Voltage PMIC5 Gen3 ADC driver for Qualcomm Technologies Inc.

\t  The driver supports reading multiple channels. The ADC is a 16-bit
\t  sigma-delta ADC. The hardware supports calibrated results for
\t  conversion requests and clients include reading phone power supply
\t  voltage, on board system thermistors connected to the PMIC ADC,
\t  PMIC die temperature, charger temperature, battery current, USB
\t  voltage input and voltage signals connected to supported PMIC GPIO
\t  pins. The hardware supports internal pull-up for thermistors and can
\t  choose between a 30k, 100k or 400k ohm pull up using the ADC channels.

\t  In addition, the same driver supports ADC thermal monitoring devices
\t  too. They appear as thermal zones with multiple trip points. A thermal
\t  client sets threshold temperature for both warm and cool trips and
\t  the ADC driver then places the hardware in the appropriate state.

\t  If compiled as a module, it will be called qcom-spmi-adc5-gen3.

'''
    anchor = 'config QCOM_VADC_COMMON\n'
    assert base.count(anchor) == 1, 'unexpected 6.14 iio/adc Kconfig layout'
    return base.replace(anchor, block + anchor)


def add_makefile(base):
    anchor = 'obj-$(CONFIG_QCOM_VADC_COMMON) += qcom-vadc-common.o\n'
    assert base.count(anchor) == 1, 'unexpected 6.14 iio/adc Makefile layout'
    return base.replace(anchor,
                        'obj-$(CONFIG_QCOM_SPMI_ADC5_GEN3) += qcom-spmi-adc5-gen3.o\n' + anchor)


def read_pinned(path, expect, label):
    data = path.read_bytes()
    got = sha(data)
    if got != expect:
        raise SystemExit(f'{label}: sha256 {got} != expected {expect}\n{path}')
    return data.decode('utf-8')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--stage', type=Path, default=DEFAULT_STAGE,
                    help='directory holding the pinned v6.14 / upstream copies')
    args = ap.parse_args()
    stage = args.stage
    v614 = stage / 'linux-6.14'

    battmgr = read_pinned(v614 / 'qcom_battmgr.c', BATTMGR_V614_SHA256, 'qcom_battmgr.c')
    kconfig = read_text_lf(v614 / 'iio-adc-Kconfig')
    makefile = read_text_lf(v614 / 'iio-adc-Makefile')
    adc = read_pinned(stage / 'upstream-qcom-spmi-adc5-gen3.c', ADC_SHA256,
                      'qcom-spmi-adc5-gen3.c')
    adc_hdr = read_pinned(stage / 'upstream-qcom-adc5-gen3-common.h',
                          ADC_HDR_SHA256, 'qcom-adc5-gen3-common.h')

    bringup = read_text_lf(ROOT / 'drivers/power/supply/qcom_battmgr.c')
    cleaned = strip_charger_init(bringup)

    patched = single_battery(cleaned)
    telemetry_patch = unified(battmgr, cleaned,
                              'a/drivers/power/supply/qcom_battmgr.c',
                              'b/drivers/power/supply/qcom_battmgr.c')
    battmgr_patch = unified(cleaned, patched,
                            'a/drivers/power/supply/qcom_battmgr.c',
                            'b/drivers/power/supply/qcom_battmgr.c')
    assert 'oneplus,xigua' in battmgr_patch
    assert 'pja110_charger_init' not in battmgr_patch + telemetry_patch

    adc_patched = adc_compat(adc)
    kconfig_patch = unified(kconfig, add_kconfig(kconfig),
                            'a/drivers/iio/adc/Kconfig', 'b/drivers/iio/adc/Kconfig')
    makefile_patch = unified(makefile, add_makefile(makefile),
                             'a/drivers/iio/adc/Makefile', 'b/drivers/iio/adc/Makefile')
    integ = kconfig_patch + makefile_patch

    (PKG / 'qcom-battmgr-pja110-telemetry.patch').write_bytes(telemetry_patch.encode())
    (PKG / 'qcom-battmgr-single-battery.patch').write_bytes(battmgr_patch.encode())
    (PKG / 'qcom-spmi-adc5-gen3-6.14.patch').write_bytes(integ.encode())
    write_text_lf(PKG / 'qcom-spmi-adc5-gen3.c', adc_patched)
    write_text_lf(PKG / 'qcom-adc5-gen3-common.h', adc_hdr)

    manifest = json.loads((PKG / 'source-manifest.json').read_text())
    manifest['local_quirk_patches'] = [
        {
            'path': 'qcom-battmgr-pja110-telemetry.patch',
            'target': 'drivers/power/supply/qcom_battmgr.c',
            'base': 'Linux v6.14 pristine',
            'base_sha256': BATTMGR_V614_SHA256,
            'sha256': sha((PKG / 'qcom-battmgr-pja110-telemetry.patch').read_bytes()),
            'scope': 'restore the verified bring-up driver behaviour: latch a failed '
                     'transaction, filter unsolicited SET replies by opcode/property, '
                     'length-check the callback, cancel enable_work on removal',
            'source_reference': 'drivers/power/supply/qcom_battmgr.c in this repository',
            'charger_init_path_included': False,
        },
        {
            'path': 'qcom-battmgr-single-battery.patch',
            'target': 'drivers/power/supply/qcom_battmgr.c',
            'base': 'Linux v6.14 + qcom-battmgr-pja110-telemetry.patch',
            'sha256': sha((PKG / 'qcom-battmgr-single-battery.patch').read_bytes()),
            'scope': 'PJA110 with an available ti,bq28z610: skip the placeholder GLINK '
                     'battery, keep USB/wireless telemetry, guard battery notifications',
            'module_version': 'pja110-single-battery-1',
        },
        {
            'path': 'qcom-spmi-adc5-gen3-6.14.patch',
            'targets': ['drivers/iio/adc/Kconfig', 'drivers/iio/adc/Makefile'],
            'base': 'Linux v6.14 pristine',
            'sha256': sha((PKG / 'qcom-spmi-adc5-gen3-6.14.patch').read_bytes()),
            'scope': 'register CONFIG_QCOM_SPMI_ADC5_GEN3 next to the in-tree '
                     'CONFIG_QCOM_VADC_COMMON module',
        },
    ]
    manifest['excluded_from_packaging'] = [
        {
            'path': 'drivers/power/supply/pja110-init.patch',
            'reason': 'experimental charger initialization (SET votes, charge enable) '
                      'and the AP gauge handshake stay out of the package; the verified '
                      'module never executed them (pja110_charger_init=0)',
        },
        {
            'path': 'drivers/power/supply/pja110-ap-gauge.h',
            'reason': 'only referenced by the excluded charger-init path',
        },
    ]
    manifest['backports'] = [
        {
            'path': 'qcom-spmi-adc5-gen3.c',
            'upstream_commit': '3857c2fe5449541e24afc5efdb0f81a8a8f9a3a0',
            'upstream_path': 'drivers/iio/adc/qcom-spmi-adc5-gen3.c',
            'upstream_sha256': ADC_SHA256,
            'sha256': sha((PKG / 'qcom-spmi-adc5-gen3.c').read_bytes()),
            'local_changes': ['drop #include <linux/device/devres.h> (post-6.14 header split)'],
        },
        {
            'path': 'qcom-adc5-gen3-common.h',
            'upstream_commit': '3857c2fe5449541e24afc5efdb0f81a8a8f9a3a0',
            'upstream_path': 'include/linux/iio/adc/qcom-adc5-gen3-common.h',
            'upstream_sha256': ADC_HDR_SHA256,
            'sha256': sha((PKG / 'qcom-adc5-gen3-common.h').read_bytes()),
            'local_changes': [],
        },
    ]
    (PKG / 'source-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps({k: manifest[k] for k in ('local_quirk_patches', 'backports')}, indent=2))


if __name__ == '__main__':
    main()
