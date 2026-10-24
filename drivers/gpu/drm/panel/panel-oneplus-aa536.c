// SPDX-License-Identifier: GPL-2.0-only
/* PJA110 experimental 60 Hz panel and minimal Iris7 analog bypass bring-up. */
#include <linux/backlight.h>
#include <linux/clk.h>
#include <linux/delay.h>
#include <linux/gpio/consumer.h>
#include <linux/module.h>
#include <linux/of.h>
#include <linux/regulator/consumer.h>
#include <drm/drm_mipi_dsi.h>
#include <drm/drm_modes.h>
#include <drm/drm_panel.h>
#include <drm/display/drm_dsc.h>
#include "panel-oneplus-aa536-cmds.h"

struct aa536 {
	struct drm_panel panel;
	struct mipi_dsi_device *dsi;
	struct drm_dsc_config dsc;
	struct regulator *vddio, *vci;
	struct gpio_desc *vout;
	struct gpio_desc *reset, *iris_reset, *iris_wakeup, *iris_ready, *iris_vdd09;
	struct clk *iris_clk;
	bool prepared;
};

static struct aa536 *to_aa536(struct drm_panel *panel)
{
	return container_of(panel, struct aa536, panel);
}

static int aa536_send(struct aa536 *ctx, const struct aa536_cmd *cmds, size_t count)
{
	size_t i;
	for (i = 0; i < count; i++) {
		struct mipi_dsi_msg msg = {
			.channel = cmds[i].channel, .type = cmds[i].type,
			.flags = MIPI_DSI_MSG_USE_LPM,
			.tx_len = cmds[i].len, .tx_buf = cmds[i].data,
		};
		ssize_t ret = ctx->dsi->host->ops->transfer(ctx->dsi->host, &msg);
		/* MSM returns padded DMA packet length, not necessarily payload length. */
		if (ret < 0) {
			dev_err(&ctx->dsi->dev, "AA536 packet %zu type=%02x failed: %zd\n", i, msg.type, ret);
			return ret;
		}
		if (cmds[i].wait_ms)
			msleep(cmds[i].wait_ms);
	}
	return 0;
}

static int aa536_iris_bypass(struct aa536 *ctx)
{
	int i, ready;
	unsigned long flags;
	/* Same reset pulse and timing as the pinned vendor iris_reset_chip(). */
	ready = gpiod_direction_output(ctx->iris_wakeup, 0);
	if (ready)
		return ready;
	ready = gpiod_direction_output(ctx->iris_reset, 1);
	if (ready)
		return ready;
	usleep_range(1000, 1100);
	gpiod_set_value_cansleep(ctx->iris_reset, 0);
	usleep_range(2000, 2100);
	ready = gpiod_get_value_cansleep(ctx->iris_ready);
	if (ready < 0)
		return ready;
	dev_info(&ctx->dsi->dev, "AA536 Iris7 after reset abyp-ready=%d\n", ready);
	if (!ready) {
		/* Vendor IRIS_FORCE_ENTER_ANALOG_BYPASS = 6; TLMM is non-sleeping. */
		local_irq_save(flags);
		for (i = 0; i < 6; i++) {
			gpiod_set_value(ctx->iris_wakeup, 1); udelay(56);
			gpiod_set_value(ctx->iris_wakeup, 0); udelay(56);
		}
		udelay(10);
		local_irq_restore(flags);
		udelay(227);
	}
	for (i = 0; i < 50; i++) {
		ready = gpiod_get_value_cansleep(ctx->iris_ready);
		if (ready < 0)
			return ready;
		if (ready == 1) {
			dev_info(&ctx->dsi->dev, "AA536 Iris7 analog bypass confirmed\n");
			return 0;
		}
		usleep_range(1000, 1100);
	}
	dev_err(&ctx->dsi->dev, "AA536 Iris7 bypass not ready; panel commands withheld\n");
	return -ETIMEDOUT;
}

static int aa536_prepare(struct drm_panel *panel)
{
	struct aa536 *ctx = to_aa536(panel);
	int ret;
	if (ctx->prepared)
		return 0;
	ret = regulator_enable(ctx->vddio);
	if (ret)
		return ret;
	usleep_range(2000, 2100);
	ret = regulator_enable(ctx->vci);
	if (ret)
		goto disable_io;
	/* Vendor panel-vout TLMM90: runtime high/cycle test produced visible bars. */
	gpiod_set_value_cansleep(ctx->vout, 1);
	ret = clk_prepare_enable(ctx->iris_clk);
	if (ret)
		goto disable_vci;
	ret = gpiod_direction_output(ctx->iris_vdd09, 1);
	if (ret)
		goto disable_clk;
	usleep_range(5000, 5100);
	ret = aa536_iris_bypass(ctx);
	if (ret)
		goto reset_iris;
	/* GPIO_ACTIVE_LOW: logical 0 means physical high, matching vendor reset. */
	ret = gpiod_direction_output(ctx->reset, 0);
	if (ret)
		goto reset_iris;
	usleep_range(2000, 2100);
	gpiod_set_value_cansleep(ctx->reset, 1);
	usleep_range(5000, 5100);
	gpiod_set_value_cansleep(ctx->reset, 0);
	msleep(25);
	ret = aa536_send(ctx, aa536_on_cmds, ARRAY_SIZE(aa536_on_cmds));
	if (ret)
		goto reset_panel;
	ctx->prepared = true;
	dev_info(&ctx->dsi->dev, "AA536 60 Hz initialization complete\n");
	return 0;
reset_panel:
	gpiod_set_value_cansleep(ctx->reset, 1);
reset_iris:
	gpiod_set_value_cansleep(ctx->iris_reset, 1);
	gpiod_set_value_cansleep(ctx->iris_vdd09, 0);
disable_clk:
	clk_disable_unprepare(ctx->iris_clk);
disable_vci:
	gpiod_set_value_cansleep(ctx->vout, 0);
	regulator_disable(ctx->vci);
disable_io:
	regulator_disable(ctx->vddio);
	return ret;
}

static int aa536_unprepare(struct drm_panel *panel)
{
	struct aa536 *ctx = to_aa536(panel);
	if (!ctx->prepared)
		return 0;
	aa536_send(ctx, aa536_off_cmds, ARRAY_SIZE(aa536_off_cmds));
	gpiod_set_value_cansleep(ctx->reset, 1);
	gpiod_set_value_cansleep(ctx->iris_reset, 1);
	gpiod_set_value_cansleep(ctx->iris_vdd09, 0);
	clk_disable_unprepare(ctx->iris_clk);
	gpiod_set_value_cansleep(ctx->vout, 0);
	msleep(5);
	regulator_disable(ctx->vci);
	msleep(23);
	regulator_disable(ctx->vddio);
	ctx->prepared = false;
	return 0;
}

static const struct drm_display_mode aa536_mode = {
	.clock = (1240 + 100 + 8 + 120) * (2772 + 20 + 2 + 30) * 60 / 1000,
	.hdisplay = 1240, .hsync_start = 1340, .hsync_end = 1348, .htotal = 1468,
	.vdisplay = 2772, .vsync_start = 2792, .vsync_end = 2794, .vtotal = 2824,
	.width_mm = 70, .height_mm = 156,
};

static int aa536_get_modes(struct drm_panel *panel, struct drm_connector *connector)
{
	struct drm_display_mode *mode = drm_mode_duplicate(connector->dev, &aa536_mode);
	if (!mode)
		return -ENOMEM;
	drm_mode_set_name(mode);
	mode->type = DRM_MODE_TYPE_DRIVER | DRM_MODE_TYPE_PREFERRED;
	connector->display_info.width_mm = mode->width_mm;
	connector->display_info.height_mm = mode->height_mm;
	connector->display_info.bpc = 10;
	drm_mode_probed_add(connector, mode);
	return 1;
}

static const struct drm_panel_funcs aa536_funcs = {
	.prepare = aa536_prepare, .unprepare = aa536_unprepare, .get_modes = aa536_get_modes,
};

static int aa536_backlight_update(struct backlight_device *bl)
{
	struct aa536 *ctx = bl_get_data(bl);
	if (!ctx->prepared)
		return 0;
	return mipi_dsi_dcs_set_display_brightness_large(ctx->dsi, backlight_get_brightness(bl));
}
static const struct backlight_ops aa536_backlight_ops = { .update_status = aa536_backlight_update };

static int aa536_probe(struct mipi_dsi_device *dsi)
{
	struct device *dev = &dsi->dev;
	struct aa536 *ctx;
	const struct backlight_properties props = { .type = BACKLIGHT_RAW, .brightness = 128, .max_brightness = 4095 };
	int ret;
	ctx = devm_kzalloc(dev, sizeof(*ctx), GFP_KERNEL);
	if (!ctx)
		return -ENOMEM;
	ctx->dsi = dsi;
	ctx->vddio = devm_regulator_get(dev, "vddio");
	if (IS_ERR(ctx->vddio))
		return dev_err_probe(dev, PTR_ERR(ctx->vddio), "vddio unavailable\n");
	ctx->vci = devm_regulator_get(dev, "vci");
	if (IS_ERR(ctx->vci))
		return dev_err_probe(dev, PTR_ERR(ctx->vci), "vci unavailable\n");
	ret = regulator_set_voltage(ctx->vddio, 1800000, 1800000);
	if (ret)
		return ret;
	ret = regulator_set_voltage(ctx->vci, 3000000, 3000000);
	if (ret)
		return ret;
#define GET_GPIO(member, name, flags) \
	ctx->member = devm_gpiod_get(dev, name, flags); \
	if (IS_ERR(ctx->member)) return dev_err_probe(dev, PTR_ERR(ctx->member), name " GPIO unavailable\n")
	GET_GPIO(reset, "reset", GPIOD_ASIS);
	GET_GPIO(vout, "vout", GPIOD_OUT_LOW);
	GET_GPIO(iris_reset, "iris-reset", GPIOD_ASIS);
	GET_GPIO(iris_wakeup, "iris-wakeup", GPIOD_ASIS);
	GET_GPIO(iris_ready, "iris-abyp-ready", GPIOD_IN);
	GET_GPIO(iris_vdd09, "iris-vdd09", GPIOD_ASIS);
#undef GET_GPIO
	if (gpiod_cansleep(ctx->iris_wakeup))
		return dev_err_probe(dev, -EINVAL, "one-wire GPIO must not sleep\n");
	ctx->iris_clk = devm_clk_get(dev, "iris");
	if (IS_ERR(ctx->iris_clk))
		return dev_err_probe(dev, PTR_ERR(ctx->iris_clk), "Iris reference clock unavailable\n");
	ctx->dsc.dsc_version_major = 1;
	ctx->dsc.dsc_version_minor = 1;
	ctx->dsc.slice_width = 620;
	ctx->dsc.slice_height = 44;
	ctx->dsc.slice_count = 2;
	ctx->dsc.bits_per_component = 10;
	ctx->dsc.bits_per_pixel = 8 << 4;
	ctx->dsc.block_pred_enable = true;
	dsi->dsc = &ctx->dsc;
	dsi->lanes = 4;
	dsi->format = MIPI_DSI_FMT_RGB888;
	dsi->mode_flags = MIPI_DSI_MODE_LPM | MIPI_DSI_CLOCK_NON_CONTINUOUS;
	drm_panel_init(&ctx->panel, dev, &aa536_funcs, DRM_MODE_CONNECTOR_DSI);
	ctx->panel.prepare_prev_first = true;
	ctx->panel.backlight = devm_backlight_device_register(dev, dev_name(dev), dev, ctx, &aa536_backlight_ops, &props);
	if (IS_ERR(ctx->panel.backlight))
		return PTR_ERR(ctx->panel.backlight);
	mipi_dsi_set_drvdata(dsi, ctx);
	drm_panel_add(&ctx->panel);
	ret = mipi_dsi_attach(dsi);
	if (ret) {
		drm_panel_remove(&ctx->panel);
		return dev_err_probe(dev, ret, "DSI attach failed\n");
	}
	dev_info(dev, "AA536 attached: 1240x2772 60Hz DSC10/SCR1; Iris bypass bring-up\n");
	return 0;
}

static void aa536_remove(struct mipi_dsi_device *dsi)
{
	struct aa536 *ctx = mipi_dsi_get_drvdata(dsi);
	drm_panel_disable(&ctx->panel);
	drm_panel_unprepare(&ctx->panel);
	mipi_dsi_detach(dsi);
	drm_panel_remove(&ctx->panel);
}

static const struct of_device_id aa536_match[] = { { .compatible = "oneplus,aa536-p-3-a0001" }, {} };
MODULE_DEVICE_TABLE(of, aa536_match);
static struct mipi_dsi_driver aa536_driver = {
	.probe = aa536_probe, .remove = aa536_remove,
	.driver = { .name = "panel-oneplus-aa536", .of_match_table = aa536_match },
};
module_mipi_dsi_driver(aa536_driver);
MODULE_DESCRIPTION("PJA110 AA536 60Hz / Iris7 analog bypass experimental panel");
MODULE_LICENSE("GPL");
