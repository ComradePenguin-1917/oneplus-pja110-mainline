"""Capture live OF properties and installed Wi-Fi power modules, read-only."""
from pathlib import Path
import subprocess
from prepare_native_install import SSH

out = Path('out/wifi-bringup-20261017')
out.mkdir(exist_ok=True)
args = SSH[:]
args[-1] = 'penguin@172.16.42.1'
args = [x if not x.startswith('UserKnownHostsFile=') else
        'UserKnownHostsFile=out/native-install-20261017/known_hosts' for x in args]
p = subprocess.run(args + ['tar -C /sys/firmware/devicetree/base -cf - soc@0/pcie@1c00000 soc@0/phy@1c06000'],
                   capture_output=True, timeout=45)
(out / ('live-devicetree.tar' if p.returncode == 0 else 'live-devicetree-partial.tar')).write_bytes(p.stdout)
print(p.stderr.decode(errors='replace'))
p.check_returncode()
cmd = '''for n in pci_pwrctl_pwrseq pwrseq_qcom_wcn ath12k; do modinfo "$n" 2>/dev/null | head -n 12; done
ls -l /sys/firmware/fdt /home/penguin/adc-test/vendor_boot_a-adc.img
sha256sum /home/penguin/adc-test/vendor_boot_a-adc.img
find /home/penguin -maxdepth 3 -name '*vendor_boot*' -o -name '*firmware*'
command -v iw; command -v rfkill
sudo -n true
'''
p = subprocess.run(args + [cmd], capture_output=True, timeout=25)
(out / 'power-module-inventory.txt').write_bytes(p.stdout + p.stderr)
print(p.stdout.decode(errors='replace'))
print(p.stderr.decode(errors='replace'))
print('Live OF archive saved:', (out / 'live-devicetree.tar').stat().st_size)
