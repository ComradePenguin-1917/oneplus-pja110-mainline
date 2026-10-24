"""Check executable generated command calls against all original vendor packets."""
import json
import re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'out/display-generator-20261013'
text=(ROOT/'drivers/gpu/drm/panel/panel-oneplus-aa536-generated.c').read_text()
expected=json.loads((OUT/'parsed-vendor-commands.json').read_text())
special={'mipi_dsi_dcs_exit_sleep_mode_multi':0x11,'mipi_dsi_dcs_enter_sleep_mode_multi':0x10,
         'mipi_dsi_dcs_set_display_on_multi':0x29,'mipi_dsi_dcs_set_display_off_multi':0x28}
summary={}
for sequence,wanted in expected.items():
    body=re.search(r'static int aa536_'+sequence+r'\(.*?\n\{(.*?)\n\}',text,re.S)[1]
    calls=re.findall(r'\b(mipi_dsi_\w+|aa536_dcs_long_write_seq)\((.*?)\);',body,re.S)
    actual=[]
    for fn,args in calls:
        if fn=='mipi_dsi_msleep':
            actual[-1]['wait_ms']=int(args.split(',')[1]);continue
        if fn=='mipi_dsi_usleep_range':
            actual[-1]['wait_ms']=int(args.split(',')[1])//1000;continue
        if fn in special:
            data=bytes([special[fn]])
        else:
            assert fn in ('mipi_dsi_dcs_write_seq_multi','aa536_dcs_long_write_seq'),fn
            data=bytes(int(v,16) for v in re.findall(r'0x([0-9a-fA-F]+)',args))
        packet_type=57 if fn=='aa536_dcs_long_write_seq' else 5 if len(data)==1 else 21 if len(data)==2 else 57
        actual.append({'type':packet_type,'channel':0,'wait_ms':0,'payload':data.hex()})
    assert actual==wanted,sequence
    summary[sequence]={'packets':len(actual),'payload_type_channel_wait_match':True}
assert '.compatible = "oneplus,aa536-p-3-a0001"' in text
assert 'ctx->dsc.bits_per_component = 10;' in text and 'ctx->dsc.slice_height = 44;' in text
assert 'ctx->dsc.slice_width = 620;' in text and '.hdisplay = 1240,' in text and '.vdisplay = 2772,' in text
summary.update(explicit_long_packet_quirks=4,verified=True)
(OUT/'command-comparison.json').write_text(json.dumps(summary,indent=2)+'\n')
print('PASS: every vendor payload, packet type, channel and delay exactly matches executable generated commands')
