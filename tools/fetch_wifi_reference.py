"""Fetch pinned OEM CNSS board-file selection logic for this device."""
from pathlib import Path
import hashlib
import json
import urllib.request
from concurrent.futures import ThreadPoolExecutor

out = Path('out/wifi-bringup-20261017/oem-source')
out.mkdir(exist_ok=True)
base = ('https://raw.githubusercontent.com/OnePlusOSS/'
        'android_kernel_modules_and_devicetree_oneplus_sm8550/'
        'f034653c086942be9398171cfa7477ddbe2d9504/'
        'vendor/qcom/opensource/wlan/platform/cnss2/')

def fetch(name):
    target = out / name
    if not target.exists():
        request = urllib.request.Request(base + name, headers={'User-Agent': 'PJA110-WiFi-bringup'})
        with urllib.request.urlopen(request, timeout=45) as response:
            target.write_bytes(response.read())
    data = target.read_bytes()
    return name, dict(url=base+name, sha256=hashlib.sha256(data).hexdigest())

with ThreadPoolExecutor(max_workers=2) as pool:
    report = dict(pool.map(fetch, ['qmi.c', 'main.c', 'pci.c', 'pci.h', 'main.h']))
(out / 'manifest.json').write_text(json.dumps(report, indent=2) + '\n')
print('OEM CNSS source saved:', ', '.join(report))
