"""Apply bounded 6.14 and proven PJA110 board adaptations to upstream output."""
import difflib
import hashlib
import json
import re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'out/display-generator-20261013'
DEST=ROOT/'drivers/gpu/drm/panel/panel-oneplus-aa536-generated.c'
raw_path=next(OUT.glob('*aa536*/panel-*.c'))
raw=raw_path.read_text()
baseline_path=OUT/'verified-panel-before.c'
if not baseline_path.exists():
    baseline_path.write_bytes((ROOT/'drivers/gpu/drm/panel/panel-oneplus-aa536.c').read_bytes())
baseline=baseline_path.read_text()
packets=json.loads((OUT/'parsed-vendor-commands.json').read_text())
def function(text,name):
    match=re.search(r'^static [^\n]*\b'+name+r'\([^\n]*\)\n\{.*?^\}',text,re.M|re.S)
    assert match,name
    return match.group()
name=re.search(r'struct (\w+) \{',raw)[1]
s=raw.replace(name,'aa536').replace('reset_gpio','reset')
s=s.replace('#include <linux/device-id/of.h>','#include <linux/of.h>')
s=s.replace('#include <linux/delay.h>','#include <linux/delay.h>\n#include <linux/clk.h>\n#include <video/mipi_display.h>')
s=s.replace('struct regulator_bulk_data *supplies;', '''struct regulator *vddio, *vci;
	struct gpio_desc *vout, *iris_reset, *iris_wakeup, *iris_ready, *iris_vdd09;
	struct clk *iris_clk;
	bool prepared;''')
s=re.sub(r'static const struct regulator_bulk_data aa536_supplies\[\] = \{.*?\};\n','',s,flags=re.S)
s=s.replace(function(s,'aa536_reset'),'')
quirks=[]
for sequence,commands in packets.items():
    for index,c in enumerate(commands):
        data=bytes.fromhex(c['payload'])
        assert c['channel']==0
        derived=5 if len(data)==1 else 21 if len(data)==2 else 57
        if c['type']!=derived:
            assert c['type']==57 and len(data)==2
            call='mipi_dsi_dcs_write_seq_multi(&dsi_ctx, '+', '.join(f'0x{b:02x}' for b in data)+');'
            body=function(s,'aa536_'+sequence)
            occurrences=[m.start() for m in re.finditer(re.escape(call),body)]
            occurrence=sum(previous['payload']==c['payload'] for previous in commands[:index])
            assert occurrence<len(occurrences),call
            offset=occurrences[occurrence]
            body2=body[:offset]+body[offset:].replace(call,call.replace('mipi_dsi_dcs_write_seq_multi','aa536_dcs_long_write_seq'),1)
            s=s.replace(body,body2)
            quirks.append({'sequence':sequence,'index':index,**c})
assert len(quirks)==4
helper='''/* Vendor explicitly uses DCS long packets for four two-byte writes.
 * Standard DCS helpers infer a short packet from that length. */
static void aa536_dcs_long_write(struct mipi_dsi_multi_context *multi,
				 const u8 *data, size_t len)
{
	struct mipi_dsi_msg msg = {
		.channel = multi->dsi->channel, .type = MIPI_DSI_DCS_LONG_WRITE,
		.flags = MIPI_DSI_MSG_USE_LPM, .tx_buf = data, .tx_len = len,
	};
	ssize_t ret;
	if (multi->accum_err)
		return;
	ret = multi->dsi->host->ops->transfer(multi->dsi->host, &msg);
	if (ret < 0)
		multi->accum_err = ret;
}
#define aa536_dcs_long_write_seq(ctx, seq...) do { \\
	static const u8 data[] = { seq }; \\
	aa536_dcs_long_write(ctx, data, sizeof(data)); \\
} while (0)

'''
s=s.replace(function(s,'aa536_on'),helper+function(s,'aa536_on'))
for fn in ('aa536_prepare','aa536_unprepare'):
    adapted=function(baseline,fn)
    adapted=adapted.replace('aa536_send(ctx, aa536_on_cmds, ARRAY_SIZE(aa536_on_cmds))','aa536_on(ctx)')
    adapted=adapted.replace('aa536_send(ctx, aa536_off_cmds, ARRAY_SIZE(aa536_off_cmds))','aa536_off(ctx)')
    s=s.replace(function(s,fn),adapted)
s=s.replace(function(s,'aa536_prepare'),function(baseline,'aa536_iris_bypass')+'\n\n'+function(s,'aa536_prepare'))
old='''ctx = devm_drm_panel_alloc(dev, struct aa536, panel,
				   &aa536_panel_funcs,
				   DRM_MODE_CONNECTOR_DSI);
	if (IS_ERR(ctx))
		return PTR_ERR(ctx);'''
assert old in s
s=s.replace(old,'''ctx = devm_kzalloc(dev, sizeof(*ctx), GFP_KERNEL);
	if (!ctx)
		return -ENOMEM;
	drm_panel_init(&ctx->panel, dev, &aa536_panel_funcs, DRM_MODE_CONNECTOR_DSI);''')
start=s.index('\tret = devm_regulator_bulk_get_const')
end=s.index('\tctx->dsi = dsi;',start)
board=function(baseline,'aa536_probe')
board=board[board.index('\tctx->vddio ='):board.index('\tctx->dsc.dsc_version_major')]
s=s[:start]+board+'\n'+s[end:]
old='''\tret = devm_drm_panel_add(dev, &ctx->panel);
	if (ret)
		return ret;'''
assert old in s
s=s.replace(old,'\tdrm_panel_add(&ctx->panel);')
s=s.replace('return devm_mipi_dsi_attach(dev, dsi);','''ret = mipi_dsi_attach(dsi);
	if (ret) {
		drm_panel_remove(&ctx->panel);
		return dev_err_probe(dev, ret, "DSI attach failed\\n");
	}
	dev_info(dev, "AA536 generator-based 60Hz driver; vendor packets and Iris bypass preserved\\n");
	return 0;''')
s=s.replace('static int aa536_bl_update_status(struct backlight_device *bl)\n'+function(s,'aa536_bl_update_status').split('\n',1)[1],'''static int aa536_bl_update_status(struct backlight_device *bl)
{
	struct mipi_dsi_device *dsi = bl_get_data(bl);
	struct aa536 *ctx = mipi_dsi_get_drvdata(dsi);
	if (!ctx->prepared)
		return 0;
	return mipi_dsi_dcs_set_display_brightness_large(dsi, backlight_get_brightness(bl));
}''')
s=s.replace('.brightness = 4095,','.brightness = 128,')
s=s.replace('MIPI_DSI_FMT_RGB101010','MIPI_DSI_FMT_RGB888')
# Preserve the validated command-mode flags, including EOT behavior.
s=re.sub(r'\tdsi->mode_flags = .*?;', '\tdsi->mode_flags = MIPI_DSI_MODE_LPM | MIPI_DSI_CLOCK_NON_CONTINUOUS;',s,flags=re.S,count=1)
# 6.14 fixed-mode helper does not populate this panel's 10bpc information.
s=s.replace('return drm_connector_helper_get_modes_fixed(connector, &aa536_mode);',
            'connector->display_info.bpc = 10;\n\treturn drm_connector_helper_get_modes_fixed(connector, &aa536_mode);')
s=s.replace('"panel,aa536-p-3-a0001-dsc"','"oneplus,aa536-p-3-a0001"')
s=s.replace('"panel-panel-aa536-p-3-a0001-dsc"','"panel-oneplus-aa536"')
# Match the already verified low-power off-command transport for this control.
s=s.replace('ctx->dsi->mode_flags &= ~MIPI_DSI_MODE_LPM;',
            'ctx->dsi->mode_flags |= MIPI_DSI_MODE_LPM;')
s=s.replace('static const struct of_device_id aa536_of_match[]',function(baseline,'aa536_remove')+'\n\nstatic const struct of_device_id aa536_of_match[]')
s=s.replace('\t.probe = aa536_probe,','\t.probe = aa536_probe,\n\t.remove = aa536_remove,')
s=s.replace('// Copyright (c) 2026 FIXME','// Generated structure reused under GPL-2.0-only; PJA110 adaptations below.')
s=s.replace('//   Copyright (c) 2013, The Linux Foundation. All rights reserved. (FIXME)',
            '// Vendor data source: OnePlus SM8550 live DT, AA536_P_3_A0001 60Hz.')
s=s.replace('linux-mdss-dsi-panel-driver-generator <fix@me>','linux-mdss-dsi-panel-driver-generator')
s=s.replace(' // FIXME','')
DEST.write_text(s,encoding='utf8')
(OUT/'panel-adaptation.patch').write_text(''.join(difflib.unified_diff(raw.splitlines(True),s.splitlines(True),fromfile='generator/'+raw_path.name,tofile=DEST.name)),encoding='utf8')
(OUT/'adaptation-manifest.json').write_text(json.dumps({'generator_output_sha256':hashlib.sha256(raw_path.read_bytes()).hexdigest(),
    'verified_panel_sha256':hashlib.sha256(baseline_path.read_bytes()).hexdigest(),
    'adapted_sha256':hashlib.sha256(DEST.read_bytes()).hexdigest(),
    'long_packet_quirks':quirks,'board_power_and_iris_preserved':True,
    'standard_generated_command_helpers_reused':True,'phone_execution_confirmed':False},indent=2)+'\n')
print('PASS: generated DRM structure adapted; 4 explicit long-packet quirks and verified board power retained')
