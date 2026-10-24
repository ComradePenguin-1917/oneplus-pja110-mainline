"""Generate the experimental driver's packet tables from the actual vendor DTB."""
import hashlib
import json
from pathlib import Path
from fdt import FDT

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'drivers/gpu/drm/panel'
OUT.mkdir(parents=True,exist_ok=True)
nodes=FDT((ROOT/'live-from-device.dtb').read_bytes()).nodes()
path=next(p for p in nodes if p.endswith('AA536_P_3_A0001_dsc_cmd/qcom,mdss-dsi-display-timings/timing@sa_fhd_60'))
text=['/* SPDX-License-Identifier: GPL-2.0-only */',
      '/* Generated from the verified PJA110 vendor live DTB, 60 Hz mode. */',
      '/* Vendor flag 0x40 is batching, not an ACK request; send synchronously. */',
      'struct aa536_cmd { u8 type, channel, wait_ms; u16 len; const u8 *data; };']
records={}
for name,prop in [('on','qcom,mdss-dsi-on-command'),('off','qcom,mdss-dsi-off-command')]:
    data=nodes[path][prop]; pos=0; commands=[]
    while pos<len(data):
        assert pos+7<=len(data)
        h=data[pos:pos+7];size=int.from_bytes(h[5:7],'big')
        payload=data[pos+7:pos+7+size]
        assert len(payload)==size and h[3] in (0,0x40) and h[0] in (0x05,0x15,0x39)
        commands.append((h[0],h[2],h[4],payload))
        pos+=7+size
    for i,(_,_,_,payload) in enumerate(commands):
        text.append(f'static const u8 aa536_{name}_{i}[] = {{ '+', '.join(f'0x{x:02x}' for x in payload)+' };')
    text.append(f'static const struct aa536_cmd aa536_{name}_cmds[] = {{')
    for i,(kind,channel,wait,payload) in enumerate(commands):
        text.append(f'\t{{ 0x{kind:02x}, {channel}, {wait}, sizeof(aa536_{name}_{i}), aa536_{name}_{i} }},')
    text.append('};')
    records[name]={'bytes':len(data),'packets':len(commands),'sha256':hashlib.sha256(data).hexdigest()}
(OUT/'panel-oneplus-aa536-cmds.h').write_text('\n'.join(text)+'\n')
(ROOT/'out/display-port-20261013/command-manifest.json').write_text(json.dumps({'vendor_mode':path,'tables':records,'vendor_batching_flag_removed':True},indent=2)+'\n')
print(records)
