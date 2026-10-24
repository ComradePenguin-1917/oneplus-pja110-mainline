"""Generate the AA536 120 Hz panel-driver variant from the live vendor DT.

The live DT (``live-from-device.dtb``) carries four timings for the AA536 panel;
this selects ``timing@sa_fhd_120`` only and runs the pinned upstream generator,
mirroring ``tools/prepare_generated_panel.py`` for the 60 Hz baseline.

Run from WSL with the generator dependencies on PYTHONPATH:

  PYTHONPATH=panel-generator-deps/python python3 tools/generate_120hz_panel.py
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
GEN = ROOT / 'out/display-generator-20261013/generator'
sys.path.insert(0, str(GEN))

from fdtwrite import parse, serialise, walk
from fdt2 import Fdt2
from panel import Panel
from generator import Options
from driver import generate_driver

OUT = ROOT / 'out/display-generator-20261013'
PANEL_SUFFIX = '/qcom,mdss_dsi_panel_AA536_P_3_A0001_dsc_cmd'
MODE = 'timing@sa_fhd_120'


def main():
    blob = (ROOT / 'live-from-device.dtb').read_bytes()
    tree, reservations = parse(blob)
    nodes = dict(walk(tree))
    matches = [p for p in nodes if p.endswith(PANEL_SUFFIX)]
    assert len(matches) == 1, matches
    panel = nodes[matches[0]]
    timings = panel.child('qcom,mdss-dsi-display-timings')
    names = [n.name for n in timings.children]
    assert MODE in names, names
    mode = next(n for n in timings.children if n.name == MODE)
    timings.children = [mode]

    vendor = OUT / 'vendor-aa536-120.dtb'
    vendor.write_bytes(serialise(tree, reservations))
    (OUT / 'generation-input-120.json').write_text(json.dumps({
        'vendor_dtb_sha256': __import__('hashlib').sha256(blob).hexdigest(),
        'panel_path': matches[0],
        'selected_mode': MODE,
        'available_modes': names,
        'selected_properties': {k: v.hex() for k, v in mode.props.items()},
    }, indent=2) + '\n')

    fdt = Fdt2(vendor.read_bytes())
    p = Panel.parse(fdt, fdt.path_offset(matches[0]))
    assert p.h.px == 1240 and p.v.px == 2772, (p.h.px, p.v.px)
    assert p.framerate == 120, p.framerate
    assert (p.dsc_slice_width, p.dsc_slice_height,
            p.dsc_bit_per_component, p.dsc_bit_per_pixel) == (620, 44, 10, 8)

    options = Options()
    options.regulator = ['vddio', 'vci']
    options.backlight = True
    options.backlight_gpio = False
    options.backlight_fallback_dcs = True
    options.dcs_get_brightness = False
    options.ignore_wait = 0
    options.dumb_dcs = True

    outdir = OUT / '120'
    outdir.mkdir(exist_ok=True)
    os.chdir(outdir)
    Path(p.id).mkdir(exist_ok=True)
    generate_driver(p, options)
    packets = {name: [{'type': c.type.value, 'channel': c.vc, 'wait_ms': c.wait,
                       'payload': c.payload.hex()} for c in commands.seq]
               for name, commands in p.cmds.items()}
    (outdir / 'parsed-vendor-commands.json').write_text(json.dumps(packets, indent=2) + '\n')
    print(json.dumps({'panel': p.id, 'mode': MODE, 'framerate': p.framerate,
                      'outdir': str(outdir), 'commands': sorted(packets)},
                     indent=2))
    print('PASS: generated AA536 120Hz driver with original vendor packets')


if __name__ == '__main__':
    main()
