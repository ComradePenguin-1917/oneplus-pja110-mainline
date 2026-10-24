"""Build the existing battmgr with a PJA110 external-gauge registration quirk."""
import difflib
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

win = Path('/mnt/h/workspace/PJA110-Mainline')
base = Path.home() / 'workspace/PJA110-Mainline/charger-native-a'
tree = base / 'linux-6.14'
build = base / 'single-battery'
out = win / 'out/battery-upower-20261017/candidate'
build.mkdir(exist_ok=True)
out.mkdir(exist_ok=True)
# Preserve the current bring-up source and its disabled opt-in charging path.
original = (win / 'drivers/power/supply/qcom_battmgr.c').read_text()
s = original
old = '\t\tpower_supply_changed(battmgr->bat_psy);'
assert s.count(old) == 1
s = s.replace(old, '\t\tif (battmgr->bat_psy)\n\t\t\tpower_supply_changed(battmgr->bat_psy);')
start = s.index('static int qcom_battmgr_probe(')
probe = s[start:]
probe = probe.replace('\tint ret;\n', '\tstruct device_node *gauge;\n\tbool external_gauge = false;\n\tint ret;\n', 1)
needle = '\tif (battmgr->variant == QCOM_BATTMGR_SC8280XP) {'
assert probe.count(needle) == 1
probe = probe.replace(needle, '''\t/* PJA110 exposes its AP-owned pack gauge separately. ADSP reports
\t * placeholder battery values, but still supplies useful USB telemetry.
\t */
\tif (of_machine_is_compatible("oneplus,xigua")) {
\t\tgauge = of_find_compatible_node(NULL, NULL, "ti,bq28z610");
\t\texternal_gauge = of_device_is_available(gauge);
\t\tof_node_put(gauge);
\t}

''' + needle)
block = '''\t\tbattmgr->bat_psy = devm_power_supply_register(dev, &sm8350_bat_psy_desc, &psy_cfg);
\t\tif (IS_ERR(battmgr->bat_psy))
\t\t\treturn dev_err_probe(dev, PTR_ERR(battmgr->bat_psy),
\t\t\t\t\t     "failed to register battery power supply\\n");'''
assert probe.count(block) == 1
probe = probe.replace(block, '\t\tif (!external_gauge) {\n' +
                      '\n'.join('\t' + line for line in block.splitlines()) +
                      '\n\t\t} else {\n\t\t\tdev_info(dev, "using external BQ28Z610 battery telemetry\\n");\n\t\t}')
s = s[:start] + probe
assert 'MODULE_VERSION(' not in s
s += '\nMODULE_VERSION("pja110-single-battery-1");\n'
(build / 'qcom_battmgr.c').write_text(s)
shutil.copyfile(win / 'drivers/power/supply/pja110-ap-gauge.h', build / 'pja110-ap-gauge.h')
(build / 'Makefile').write_text('obj-m += qcom_battmgr.o\n')
patch = ''.join(difflib.unified_diff(original.splitlines(True), s.splitlines(True),
    fromfile='a/qcom_battmgr.c', tofile='b/qcom_battmgr.c'))
(out / 'single-battery.patch').write_text(patch)
(out / 'qcom_battmgr.c').write_text(s)
command = ['make', '-C', str(tree), 'ARCH=arm64',
           'CROSS_COMPILE=/opt/aarch64-linux-gnu-toolchain-13.3/bin/aarch64-none-linux-gnu-',
           'M=' + str(build), 'modules']
p = subprocess.run(command, capture_output=True)
(out / 'build.log').write_bytes(p.stdout + p.stderr)
print((p.stdout + p.stderr).decode(errors='replace'))
p.check_returncode()
data = (build / 'qcom_battmgr.ko').read_bytes()
(out / 'qcom_battmgr.ko').write_bytes(data)
report = dict(sha256=hashlib.sha256(data).hexdigest(),
              source_base_sha256=hashlib.sha256(original.encode()).hexdigest(),
              version='pja110-single-battery-1', strict_module_link_passed=True,
              scope='PJA110 with enabled ti,bq28z610: skip only GLINK battery registration; guard battery notification',
              charger_init_parameter_stays_disabled=True, phone_tested=False)
(out / 'manifest.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report, indent=2))
