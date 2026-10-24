"""Extract pinned upstream ADC sources without changing the working kernel."""
from pathlib import Path
import hashlib
import json
import subprocess
root = Path(__file__).resolve().parents[1]
repo = root / 'linux'
commit = '3857c2fe5449541e24afc5efdb0f81a8a8f9a3a0'
out = root / 'out/native-install-20261017/adc-gen3'
paths = ['drivers/iio/adc/qcom-spmi-adc5-gen3.c',
         'include/linux/iio/adc/qcom-adc5-gen3-common.h',
         'Documentation/devicetree/bindings/iio/adc/qcom,spmi-adc5-gen3.yaml']
records = []
for path in paths:
    data = subprocess.run(['git', '-C', str(repo), 'show', commit + ':' + path],
                          check=True, capture_output=True).stdout
    dest = out / 'upstream' / path
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    records.append(dict(path=path, sha256=hashlib.sha256(data).hexdigest()))
(out / 'source.json').write_text(json.dumps(dict(repository='https://github.com/torvalds/linux', commit=commit, files=records), indent=2) + '\n')
print('Extracted pinned upstream source:', commit)
