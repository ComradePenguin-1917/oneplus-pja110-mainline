"""Strict external-module compatibility build, leaving A config untouched."""
from pathlib import Path
import subprocess
import shutil
import hashlib
import json
import difflib
root = Path.home() / 'workspace/PJA110-Mainline/charger-native-a'
tree = root / 'linux-6.14'
out = Path('/mnt/h/workspace/PJA110-Mainline/out/native-install-20261017/adc-gen3')
build = root / 'adc-gen3'
build.mkdir(exist_ok=True)
source = (out / 'upstream/drivers/iio/adc/qcom-spmi-adc5-gen3.c').read_text()
source = source.replace('#include <linux/device/devres.h>\n', '')
(build / 'qcom-spmi-adc5-gen3.c').write_text(source)
header = build / 'include/linux/iio/adc/qcom-adc5-gen3-common.h'
header.parent.mkdir(parents=True, exist_ok=True)
shutil.copyfile(out / 'upstream/include/linux/iio/adc/qcom-adc5-gen3-common.h', header)
shutil.copyfile(tree / 'drivers/iio/adc/qcom-vadc-common.c', build / 'qcom-vadc-common.c')
(build / 'Makefile').write_text('obj-m += qcom-spmi-adc5-gen3.o qcom-vadc-common.o\nccflags-y += -I$(src)/include\n')
cmd = ['make', '-C', str(tree), 'ARCH=arm64',
       'CROSS_COMPILE=/opt/aarch64-linux-gnu-toolchain-13.3/bin/aarch64-none-linux-gnu-',
       'M=' + str(build), 'modules']
p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
(out / 'build.log').write_bytes(p.stdout)
print(p.stdout.decode(errors='replace'))
p.check_returncode()
shutil.copyfile(build / 'qcom-spmi-adc5-gen3.ko', out / 'qcom-spmi-adc5-gen3.ko')
shutil.copyfile(build / 'qcom-vadc-common.ko', out / 'qcom-vadc-common.ko')
original = (out / 'upstream/drivers/iio/adc/qcom-spmi-adc5-gen3.c').read_text()
(out / 'linux-6.14-compat.patch').write_text(''.join(difflib.unified_diff(original.splitlines(True), source.splitlines(True), fromfile='a/drivers/iio/adc/qcom-spmi-adc5-gen3.c', tofile='b/drivers/iio/adc/qcom-spmi-adc5-gen3.c')))
report = dict(strict_module_link_passed=True, kernel_release=(tree / 'include/config/kernel.release').read_text().strip(),
              phone_installed=False, runtime_sensor_verified=False,
              modules={name: hashlib.sha256((out / name).read_bytes()).hexdigest() for name in ('qcom-spmi-adc5-gen3.ko', 'qcom-vadc-common.ko')})
(out / 'build-result.json').write_text(json.dumps(report, indent=2) + '\n')
win = Path('/mnt/h/workspace/PJA110-Mainline')
candidate = build / 'pja110-adc-candidate.dts'
candidate.write_text((win / 'dts/sm8550-oneplus-xigua.dts').read_text() + '\n' + (win / 'dts/sm8550-oneplus-xigua-adc-candidate.dtsi').read_text())
preprocessed = build / 'pja110-adc-candidate.pp.dts'
cpp = ['/opt/aarch64-linux-gnu-toolchain-13.3/bin/aarch64-none-linux-gnu-gcc', '-E', '-P', '-x', 'assembler-with-cpp', '-nostdinc', '-undef', '-D__DTS__', '-I' + str(win / 'dts'), '-I' + str(tree / 'arch/arm64/boot/dts/qcom'), '-I' + str(tree / 'scripts/dtc/include-prefixes'), '-I' + str(tree / 'include'), str(candidate), '-o', str(preprocessed)]
subprocess.run(cpp, check=True)
p = subprocess.run([str(tree / 'scripts/dtc/dtc'), '-I', 'dts', '-O', 'dtb', '-o', str(out / 'candidate.dtb'), str(preprocessed)], capture_output=True)
(out / 'dtc.log').write_bytes(p.stdout + p.stderr)
p.check_returncode()
report['device_tree_compile_passed'] = True
(out / 'build-result.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report, indent=2))
