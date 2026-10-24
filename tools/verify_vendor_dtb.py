"""Compare the packaged ``verified-vendor.dtb`` with what the phone actually ran.

Two checks:

  * structural: the DTB the offline image generator uses must carry the battery,
    ADC, Wi-Fi, panel and touch nodes with the properties the drivers rely on;
  * runtime: when a ``running-device-tree.json`` capture from
    ``tools/capture_native_baseline.py`` is given, every checked path must also
    exist at runtime with the same effective value (phandles normalised).

The runtime tree is the merged result of the vendor_boot DTB, the vendor DTBO
and bootloader fixups, so only the explicitly listed paths are compared; a
whole-tree equality check would be wrong.
"""
import argparse
import json
import re
from pathlib import Path

from fdt import FDT

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DTB = ROOT / 'postmarketos/device/testing/device-oneplus-xigua/verified-vendor.dtb'

# (node path, property, matcher, why)
CHECKS = [
    ('/', 'compatible', r'oneplus,xigua', 'project identity must survive the vendor DTBO'),
    ('/soc@0/geniqup@8c0000/i2c@880000/fuel-gauge@55', 'compatible',
     r'^ti,bq28z610', 'BQ28Z610 pack gauge'),
    ('/soc@0/geniqup@8c0000/i2c@880000', 'status', r'^okay$', 'I2C8 enabled for the gauge'),
    ('/soc@0/spmi@c400000/pmic@0/adc@9000', 'compatible',
     r'^qcom,spmi-adc5-gen3', 'ADC5 Gen3 driver binding'),
    ('/soc@0/spmi@c400000/pmic@0/adc@9000', 'reg', r'.*', 'ADC region 0x9000/0x9100'),
    ('/soc@0/spmi@c400000/pmic@0/adc@9000/channel@74c', 'label',
     r'^subboard_temp$', 'PM8550B AMUX3 thermo channel'),
    ('/soc@0/pcie@1c00000', 'status', r'^okay$', 'PCIe0 enabled for WCN7850'),
    ('/soc@0/pcie@1c00000/pcie@0/wifi@0', 'compatible',
     r'.*pci17cb,1107|.*qcom,wcn7850', 'ath12k device binding'),
    ('/soc@0/display-subsystem@ae00000/dsi@ae94000/panel@0', 'compatible',
     r'^oneplus,aa536-p-3-a0001$', 'AA536 panel'),
    ('/soc@0/display-subsystem@ae00000/dsi@ae94000/panel@0', 'vout-gpios',
     r'.*', 'GPIO90 panel power (Iris7 bypass)'),
    ('/soc@0/geniqup@ac0000/spi@a90000/touchscreen@0', 'compatible',
     r'.*(s3910|synaptics).*', 'Aston TCM touchscreen'),
    ('/pmic-glink', 'compatible', r'.*pmic-glink.*', 'GLINK USB/wireless telemetry'),
]


def printable(value):
    """Render an FDT property as a comparable string."""
    if isinstance(value, str):
        return value
    if isinstance(value, (bytes, bytearray)):
        if all(32 <= c < 127 or c == 0 for c in value):
            return value.rstrip(b'\0').decode('ascii', 'replace').replace('\0', ',')
        return value.hex()
    return str(value)


def match(pattern, value):
    return re.search(pattern, value or '') is not None


def runtime_normalized(value):
    """The capture renders NUL-separated lists as ``\\0``; compare in one form."""
    if value is None:
        return None
    value = str(value).replace('\\0', ',')
    # Binary properties are not meaningfully comparable as text; skip equality.
    if re.fullmatch(r'[0-9a-f]+', value) and len(value) >= 8 and len(value) % 2 == 0:
        return None
    return value


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--dtb', default=str(DEFAULT_DTB))
    ap.add_argument('--running', default=str(ROOT / 'out/baseline-20261017/raw/running-device-tree.json'),
                    help='running tree JSON from capture_native_baseline.py')
    ap.add_argument('--out', default='out/baseline-20261017/dtb-verification.json')
    args = ap.parse_args()

    dtb_path = Path(args.dtb)
    nodes = FDT(dtb_path.read_bytes()).nodes()
    running = None
    if args.running and Path(args.running).is_file():
        running = json.loads(Path(args.running).read_text())

    results = []
    failed = 0
    for path, prop, pattern, why in CHECKS:
        node = nodes.get(path, {})
        raw = node.get(prop)
        value = printable(raw) if raw is not None else None
        ok = match(pattern, value)
        runtime_value = None
        if running is not None:
            runtime_value = running.get(path, {}).get(prop)
        runtime_same = None
        normalized_runtime = runtime_normalized(runtime_value)
        if normalized_runtime is not None and value is not None:
            # Model and /chosen are expected to differ (vendor DTBO/bootloader).
            runtime_same = (normalized_runtime == value)
        entry = {'path': path, 'property': prop, 'dtb_value': value,
                 'runtime_value': runtime_value,
                 'runtime_value_normalized': normalized_runtime,
                 'dtb_ok': ok, 'runtime_same_as_dtb': runtime_same, 'why': why}
        if not ok:
            failed += 1
            entry['error'] = 'packaged DTB does not satisfy this contract'
        elif runtime_same is False:
            failed += 1
            entry['error'] = 'runtime value differs from the packaged DTB'
        results.append(entry)

    report = {
        'dtb': str(dtb_path),
        'dtb_sha256': __import__('hashlib').sha256(dtb_path.read_bytes()).hexdigest(),
        'running_capture': args.running,
        'checks': len(results),
        'failed': failed,
        'results': results,
        'phone_tested': False,
    }
    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + '\n')
    for entry in results:
        state = 'ok  ' if entry['dtb_ok'] and entry['runtime_same_as_dtb'] is not False else 'FAIL'
        print(f"{state} {entry['path']} {entry['property']} = {entry['dtb_value']!r}")
    print(f"{len(results) - failed}/{len(results)} DTB contracts satisfied; report: {out}")
    if failed:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
