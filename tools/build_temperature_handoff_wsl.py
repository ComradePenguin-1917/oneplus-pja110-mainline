"""Build a one-shot OEM temperature-property test, with no charger controls."""
from pathlib import Path
import subprocess
import hashlib
import json
import difflib
win = Path('/mnt/h/workspace/PJA110-Mainline')
root = Path.home() / 'workspace/PJA110-Mainline/charger-native-a'
tree = root / 'linux-6.14'
build = root / 'temperature-handoff'
out = win / 'out/native-install-20261017/temperature-handoff'
out.mkdir(exist_ok=True)
build.mkdir(exist_ok=True)
original = (win / 'drivers/power/supply/qcom_battmgr.c').read_text()
s = original
start = s.index('static bool pja110_charger_init;')
end = s.index('#define BATTMGR_CHEMISTRY_LEN', start)
s = s[:start] + '''static int pja110_match_temp = -10000;
module_param(pja110_match_temp, int, 0400);
static int temperature_result = -EINPROGRESS;
module_param(temperature_result, int, 0444);
static bool temperature_attempted;
#include <linux/soc/qcom/smem.h>
#include <linux/unaligned.h>

''' + s[end:]
start = s.index('/* Gated downstream initialization')
end = s.index('static void qcom_battmgr_enable_worker', start)
s = s[:start] + '''/* One-shot property 29, reused from factory matched-temperature setter.
 * This module has no input-current or charge-enable SET path.
 * Caller supplies a fresh, validated subboard ADC sample in deci-degrees.
 */
static int qcom_battmgr_pja110_init(struct qcom_battmgr *b)
{
    const void *project;
    size_t size;
    int ret;

    if (pja110_match_temp == -10000 || temperature_attempted)
        return 0;
    temperature_attempted = true;
    ret = -ENODEV;
    if (!of_machine_is_compatible("oneplus,xigua") ||
        b->variant != QCOM_BATTMGR_SM8350 || !b->service_up)
        goto done;
    project = qcom_smem_get(QCOM_SMEM_HOST_ANY, 135, &size);
    if (IS_ERR(project)) {
        ret = PTR_ERR(project);
        goto done;
    }
    if (size < 8 || get_unaligned_le32((const u8 *)project + 4) != 22851)
        goto done;
    ret = -ERANGE;
    if (pja110_match_temp < 100 || pja110_match_temp > 400)
        goto done;
    ret = pja110_ap_gauge_check(b->dev);
    if (ret)
        goto done;
    ret = qcom_battmgr_request_property(b, BATTMGR_BAT_PROPERTY_SET,
                                       29, pja110_match_temp);
done:
    WRITE_ONCE(temperature_result, ret);
    dev_info(b->dev, "PJA110 one-shot matched temperature: dC=%d result=%d\\n",
             pja110_match_temp, ret);
    return ret;
}

''' + s[end:]
assert 'BATT_CHG_EN' not in s
assert 'USB_INPUT_CURR_LIMIT, 500000' not in s
(build / 'qcom_battmgr.c').write_text(s)
(build / 'pja110-ap-gauge.h').write_bytes((win / 'drivers/power/supply/pja110-ap-gauge.h').read_bytes())
(build / 'Makefile').write_text('obj-m += qcom_battmgr.o\n')
p = subprocess.run(['make', '-C', str(tree), 'ARCH=arm64',
    'CROSS_COMPILE=/opt/aarch64-linux-gnu-toolchain-13.3/bin/aarch64-none-linux-gnu-',
    'M=' + str(build), 'modules'], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
(out / 'build.log').write_bytes(p.stdout)
print(p.stdout.decode(errors='replace'))
p.check_returncode()
data = (build / 'qcom_battmgr.ko').read_bytes()
(out / 'qcom_battmgr-temperature.ko').write_bytes(data)
(out / 'qcom_battmgr-temperature.c').write_text(s)
(out / 'temperature-only.patch').write_text(''.join(difflib.unified_diff(original.splitlines(True), s.splitlines(True))))
report = dict(strict_link_passed=True, module_sha256=hashlib.sha256(data).hexdigest(),
    only_oem_set_property=29, charge_enable=False, usb_current_writes=False,
    gauge_init=False, live_tested=False, continuous_temperature_policy=False)
(out / 'build-result.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report, indent=2))
