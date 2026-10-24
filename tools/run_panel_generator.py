"""Run the pinned upstream parser/generator on the selected original vendor node."""
import json
import os
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'out/display-generator-20261013'
sys.path.insert(0,str(OUT/'generator'))
from fdt2 import Fdt2
from panel import Panel
from generator import Options
from driver import generate_driver

metadata=json.loads((OUT/'generation-input.json').read_text())
fdt=Fdt2((OUT/'vendor-aa536-60.dtb').read_bytes())
p=Panel.parse(fdt,fdt.path_offset(metadata['panel_path']))
assert p.h.px==1240 and p.v.px==2772 and p.framerate==60
assert p.dsc_version==0x11 and p.dsc_scr_version==1
assert (p.dsc_slice_width,p.dsc_slice_height,p.dsc_bit_per_component,p.dsc_bit_per_pixel)==(620,44,10,8)
options=Options()
options.regulator=['vddio','vci'];options.backlight=True
options.backlight_gpio=False;options.backlight_fallback_dcs=True
options.dcs_get_brightness=False;options.ignore_wait=0;options.dumb_dcs=True
os.chdir(OUT)
Path(p.id).mkdir(exist_ok=True)
generate_driver(p,options)
packets={name:[{'type':c.type.value,'channel':c.vc,'wait_ms':c.wait,'payload':c.payload.hex()} for c in commands.seq] for name,commands in p.cmds.items()}
(OUT/'parsed-vendor-commands.json').write_text(json.dumps(packets,indent=2)+'\n')
print('PASS: upstream generator produced AA536 60Hz driver with original packets')
