"""Pin generator inputs and select only the verified AA536 60Hz mode."""
import difflib
import hashlib
import json
from pathlib import Path
from fdtwrite import parse, serialise, walk

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'out/display-generator-20261013'
GEN=ROOT/'out/display-touch-reuse-20261013/panel-generator'
OUT.mkdir(exist_ok=True)
copy=OUT/'generator';copy.mkdir(exist_ok=True)
manifest=json.loads((GEN.parent/'panel-generator-manifest.json').read_text())
for item in manifest['files']:
    raw=(GEN/item['path']).read_bytes()
    assert hashlib.sha256(raw).hexdigest()==item['sha256']
    edited=raw.decode().replace('\r\n','\n')
    if item['path']=='driver.py':
        # Python <=3.11 disallows a backslash inside an f-string expression.
        old="{wrap.join('\tdsi->mode_flags = ', ' |', ';', p.flags)}"
        assert edited.count(old)==1
        edited=edited.replace(old,'{mode_flags}')
        anchor='def generate_probe(p: Panel, options: Options) -> str:\n'
        assert edited.count(anchor)==1
        edited=edited.replace(anchor,anchor+"\tmode_flags = wrap.join('\\tdsi->mode_flags = ', ' |', ';', p.flags)\n")
    (copy/item['path']).write_text(edited,encoding='utf8')
    if edited!=raw.decode():
        (OUT/(item['path']+'.patch')).write_text(''.join(difflib.unified_diff(raw.decode().splitlines(True),edited.splitlines(True),fromfile='upstream/'+item['path'],tofile='compatible/'+item['path'])),encoding='utf8')
blob=(ROOT/'live-from-device.dtb').read_bytes()
tree,reservations=parse(blob)
nodes=dict(walk(tree))
matches=[p for p in nodes if p.endswith('/qcom,mdss_dsi_panel_AA536_P_3_A0001_dsc_cmd')]
assert len(matches)==1
panel=nodes[matches[0]]
timings=panel.child('qcom,mdss-dsi-display-timings')
mode=next(n for n in timings.children if n.name=='timing@sa_fhd_60')
timings.children=[mode]
# Keep the full tree for phandle resolution; generation selects this panel only.
(OUT/'vendor-aa536-60.dtb').write_bytes(serialise(tree,reservations))
(OUT/'generation-input.json').write_text(json.dumps({'generator':manifest,
    'vendor_dtb_sha256':hashlib.sha256(blob).hexdigest(),'panel_path':matches[0],
    'selected_mode':mode.name,'selected_properties':{k:v.hex() for k,v in mode.props.items()}},indent=2)+'\n')
print('PASS: pinned generator and original AA536 60Hz properties prepared')
