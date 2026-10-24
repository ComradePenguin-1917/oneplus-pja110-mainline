// SPDX-License-Identifier: GPL-2.0-only
// Generated structure reused under GPL-2.0-only; PJA110 adaptations below.
// Generated with linux-mdss-dsi-panel-driver-generator from vendor device tree:
// Vendor data source: OnePlus SM8550 live DT, AA536_P_3_A0001 60Hz.

#include <linux/backlight.h>
#include <linux/delay.h>
#include <linux/clk.h>
#include <video/mipi_display.h>
#include <linux/of.h>
#include <linux/gpio/consumer.h>
#include <linux/module.h>
#include <linux/regulator/consumer.h>

#include <drm/display/drm_dsc.h>
#include <drm/display/drm_dsc_helper.h>
#include <drm/drm_mipi_dsi.h>
#include <drm/drm_modes.h>
#include <drm/drm_panel.h>
#include <drm/drm_probe_helper.h>

struct aa536 {
	struct drm_panel panel;
	struct mipi_dsi_device *dsi;
	struct drm_dsc_config dsc;
	struct regulator *vddio, *vci;
	struct gpio_desc *vout, *iris_reset, *iris_wakeup, *iris_ready, *iris_vdd09;
	struct clk *iris_clk;
	bool prepared;
	struct gpio_desc *reset;
};


static inline
struct aa536 *to_aa536(struct drm_panel *panel)
{
	return container_of_const(panel, struct aa536, panel);
}



/* Vendor explicitly uses DCS long packets for four two-byte writes.
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
#define aa536_dcs_long_write_seq(ctx, seq...) do { \
	static const u8 data[] = { seq }; \
	aa536_dcs_long_write(ctx, data, sizeof(data)); \
} while (0)

static int aa536_on(struct aa536 *ctx)
{
	struct mipi_dsi_multi_context dsi_ctx = { .dsi = ctx->dsi };

	ctx->dsi->mode_flags |= MIPI_DSI_MODE_LPM;

	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xf0,
				     0x55, 0xaa, 0x52, 0x08, 0x04);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xff, 0xaa, 0x55, 0xa5, 0x80);
	aa536_dcs_long_write_seq(&dsi_ctx, 0x6f, 0x1a);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xf4, 0x55);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0x6f, 0x11);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xf8, 0x01, 0x4e);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0x6f, 0x2d);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xf8, 0x00, 0xfc);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xff, 0xaa, 0x55, 0xa5, 0x81);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0x6f, 0x05);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xfe, 0x3c);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0x6f, 0x02);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xf9, 0x04);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0x6f, 0x1e);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xfb, 0x0f);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xff, 0xaa, 0x55, 0xa5, 0x82);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0x6f, 0x09);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xf2, 0x55);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xff, 0xaa, 0x55, 0xa5, 0x83);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0x6f, 0x12);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xfe, 0x41);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0x6f, 0x13);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xfd, 0x21);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0x35);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0x53, 0x20);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0x2a, 0x00, 0x00, 0x04, 0xd7);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0x2b, 0x00, 0x00, 0x0a, 0xd3);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0x26, 0x00);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0x81, 0x01, 0x00);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0x03, 0x01);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0x90, 0x03, 0x03);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0x91,
				     0xab, 0x28, 0x00, 0x2c, 0xf2, 0x00, 0x02,
				     0x85, 0x04, 0x06, 0x00, 0x08, 0x02, 0xcb,
				     0x01, 0xff, 0x10, 0xe0);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xff, 0xaa, 0x55, 0xa5, 0x81);
	aa536_dcs_long_write_seq(&dsi_ctx, 0x6f, 0x24);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xfb,
				     0x00, 0x03, 0x04, 0x55, 0x77, 0x77, 0x77,
				     0x99, 0x9d, 0x00, 0x00, 0x06, 0x88, 0x9a,
				     0xbb, 0xbc, 0xde, 0xef, 0xf0, 0x11);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xf0,
				     0x55, 0xaa, 0x52, 0x08, 0x01);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0x6f, 0x0e);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xd2, 0x00);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xf0,
				     0x55, 0xaa, 0x52, 0x08, 0x01);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0x6f, 0x02);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xd2, 0x01, 0x01, 0x2d);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0x6f, 0x05);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xd2, 0x01, 0x01, 0x00);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0x6f, 0x01);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xe4, 0x10, 0x10, 0x01, 0x00);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0x6f, 0x0b);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xe4, 0x00, 0x10, 0x00, 0x00);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xf0,
				     0x55, 0xaa, 0x52, 0x08, 0x03);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xc7, 0x00);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0x2f, 0x00);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xf0,
				     0x55, 0xaa, 0x52, 0x08, 0x0a);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0x6f, 0x6b);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xb0, 0x01);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0x44, 0x0a, 0xc0);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xf0,
				     0x55, 0xaa, 0x52, 0x08, 0x00);
	aa536_dcs_long_write_seq(&dsi_ctx, 0x6f, 0x2d);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xb5,
				     0x28, 0x28, 0x28, 0x28, 0x28, 0x28, 0x28,
				     0x28, 0x28, 0x28, 0x28, 0x28, 0x28, 0x28,
				     0x27, 0x27, 0x24, 0x24, 0x12, 0x12, 0x12,
				     0x12, 0x12);
	aa536_dcs_long_write_seq(&dsi_ctx, 0x6f, 0x44);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xb5,
				     0x28, 0x28, 0x28, 0x28, 0x28, 0x28, 0x28,
				     0x28, 0x28, 0x28, 0x28, 0x28, 0x28, 0x28,
				     0x27, 0x27, 0x24, 0x24, 0x12, 0x12, 0x12,
				     0x12, 0x12);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xf0,
				     0x55, 0xaa, 0x52, 0x08, 0x00);
	mipi_dsi_dcs_exit_sleep_mode_multi(&dsi_ctx);
	mipi_dsi_msleep(&dsi_ctx, 120);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0x35, 0x00, 0x00, 0x00, 0x01);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xf0,
				     0x55, 0xaa, 0x52, 0x08, 0x01);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xc3,
				     0xdd, 0x06, 0x20, 0x11, 0xfc, 0x00, 0x06,
				     0x20, 0x11, 0xff, 0x00, 0x03, 0xf2, 0x12,
				     0x05, 0x43, 0x18, 0x03, 0xf2, 0x12, 0x05,
				     0x43, 0x18, 0x03, 0xf2, 0x12, 0x05, 0x43,
				     0x18, 0x03, 0xf2, 0x12, 0x05, 0x43, 0x18,
				     0x03, 0xf2, 0x12, 0x05, 0x43, 0x18);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xf0,
				     0x55, 0xaa, 0x52, 0x08, 0x00);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0x6f, 0x1b);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xba, 0x18);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0x6f, 0x1c);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xba,
				     0x01, 0x01, 0x01, 0x01, 0x00, 0x01, 0x01,
				     0x03, 0x00, 0x01, 0x02, 0x03, 0x00, 0x00,
				     0x00, 0x00);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0x6f, 0x2c);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xba,
				     0x01, 0x01, 0x01, 0x01, 0x00, 0x01, 0x01,
				     0x03, 0x00, 0x01, 0x02, 0x03, 0x00, 0x00,
				     0x00, 0x00);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0x6f, 0x3c);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xba,
				     0x01, 0x01, 0x01, 0x01, 0x00, 0x01, 0x01,
				     0x03, 0x00, 0x01, 0x02, 0x03, 0x00, 0x00,
				     0x00, 0x00);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0x6f, 0x4c);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xba,
				     0x01, 0x01, 0x01, 0x01, 0x00, 0x01, 0x01,
				     0x03, 0x00, 0x01, 0x02, 0x03, 0x00, 0x00,
				     0x00, 0x00);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0x6f, 0x5c);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xba, 0x01, 0x01, 0x01, 0x01);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0x6f, 0x6c);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xba, 0x00, 0x01, 0x02, 0x03);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0x6f, 0x7c);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xba, 0x00, 0x01, 0x02, 0x03);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0x6f, 0x8c);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xba, 0x00, 0x00, 0x00, 0x00);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0x6f, 0x9c);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xba,
				     0x11, 0x1f, 0x11, 0x1f, 0x11, 0x1f, 0x11,
				     0x1f);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0x6f, 0xa4);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xba, 0xe4);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0x6f, 0xa8);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xba, 0x00, 0x00);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0x6f, 0xb0);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xba, 0x00, 0x00, 0x00, 0x00);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0x2f, 0x30);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0x6d, 0x01);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xf0,
				     0x55, 0xaa, 0x52, 0x08, 0x01);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xe5, 0xb2, 0x26);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0x6f, 0x22);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xe5, 0xb2, 0x26);
	mipi_dsi_dcs_set_display_on_multi(&dsi_ctx);

	return dsi_ctx.accum_err;
}

static int aa536_off(struct aa536 *ctx)
{
	struct mipi_dsi_multi_context dsi_ctx = { .dsi = ctx->dsi };

	ctx->dsi->mode_flags |= MIPI_DSI_MODE_LPM;

	mipi_dsi_dcs_set_display_off_multi(&dsi_ctx);
	mipi_dsi_msleep(&dsi_ctx, 20);
	mipi_dsi_dcs_enter_sleep_mode_multi(&dsi_ctx);
	mipi_dsi_msleep(&dsi_ctx, 120);

	return dsi_ctx.accum_err;
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
	ret = aa536_on(ctx);
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
	aa536_off(ctx);
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
	.hdisplay = 1240,
	.hsync_start = 1240 + 100,
	.hsync_end = 1240 + 100 + 8,
	.htotal = 1240 + 100 + 8 + 120,
	.vdisplay = 2772,
	.vsync_start = 2772 + 20,
	.vsync_end = 2772 + 20 + 2,
	.vtotal = 2772 + 20 + 2 + 30,
	.width_mm = 70,
	.height_mm = 156,
	.type = DRM_MODE_TYPE_DRIVER,
};

static int aa536_get_modes(struct drm_panel *panel,
					       struct drm_connector *connector)
{
	connector->display_info.bpc = 10;
	return drm_connector_helper_get_modes_fixed(connector, &aa536_mode);
}

static const struct drm_panel_funcs aa536_panel_funcs = {
	.prepare = aa536_prepare,
	.unprepare = aa536_unprepare,
	.get_modes = aa536_get_modes,
};

static int aa536_bl_update_status(struct backlight_device *bl)
{
	struct mipi_dsi_device *dsi = bl_get_data(bl);
	struct aa536 *ctx = mipi_dsi_get_drvdata(dsi);
	if (!ctx->prepared)
		return 0;
	return mipi_dsi_dcs_set_display_brightness_large(dsi, backlight_get_brightness(bl));
}

static const struct backlight_ops aa536_bl_ops = {
	.update_status = aa536_bl_update_status,
};

static struct backlight_device *
aa536_create_backlight(struct mipi_dsi_device *dsi)
{
	struct device *dev = &dsi->dev;
	const struct backlight_properties props = {
		.type = BACKLIGHT_RAW,
		.brightness = 128,
		.max_brightness = 4095,
	};

	return devm_backlight_device_register(dev, dev_name(dev), dev, dsi,
					      &aa536_bl_ops, &props);
}

static int aa536_probe(struct mipi_dsi_device *dsi)
{
	struct device *dev = &dsi->dev;
	struct aa536 *ctx;
	int ret;

	ctx = devm_kzalloc(dev, sizeof(*ctx), GFP_KERNEL);
	if (!ctx)
		return -ENOMEM;
	drm_panel_init(&ctx->panel, dev, &aa536_panel_funcs, DRM_MODE_CONNECTOR_DSI);

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

	ctx->dsi = dsi;
	mipi_dsi_set_drvdata(dsi, ctx);

	dsi->lanes = 4;
	dsi->format = MIPI_DSI_FMT_RGB888;
	dsi->mode_flags = MIPI_DSI_MODE_LPM | MIPI_DSI_CLOCK_NON_CONTINUOUS;

	ctx->panel.prepare_prev_first = true;

	ret = drm_panel_of_backlight(&ctx->panel);
	if (ret)
		return dev_err_probe(dev, ret, "Failed to get backlight\n");

	/* Fallback to DCS backlight if no backlight is defined in DT */
	if (!ctx->panel.backlight) {
		ctx->panel.backlight = aa536_create_backlight(dsi);
		if (IS_ERR(ctx->panel.backlight))
			return dev_err_probe(dev, PTR_ERR(ctx->panel.backlight),
					     "Failed to create backlight\n");
	}

	drm_panel_add(&ctx->panel);

	/* This panel only supports DSC; unconditionally enable it */
	dsi->dsc = &ctx->dsc;

	ctx->dsc.dsc_version_major = 1;
	ctx->dsc.dsc_version_minor = 1;

	/* TODO: Pass slice_per_pkt = 2 */
	ctx->dsc.slice_height = 44;
	ctx->dsc.slice_width = 620;
	/*
	 * TODO: hdisplay should be read from the selected mode once
	 * it is passed back to drm_panel (in prepare?)
	 */
	WARN_ON(1240 % ctx->dsc.slice_width);
	ctx->dsc.slice_count = 1240 / ctx->dsc.slice_width;
	ctx->dsc.bits_per_component = 10;
	ctx->dsc.bits_per_pixel = 8 << 4; /* 4 fractional bits */
	ctx->dsc.block_pred_enable = true;

	ret = mipi_dsi_attach(dsi);
	if (ret) {
		drm_panel_remove(&ctx->panel);
		return dev_err_probe(dev, ret, "DSI attach failed\n");
	}
	dev_info(dev, "AA536 generator-based 60Hz driver; vendor packets and Iris bypass preserved\n");
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

static const struct of_device_id aa536_of_match[] = {
	{ .compatible = "oneplus,aa536-p-3-a0001" },
	{ /* sentinel */ }
};
MODULE_DEVICE_TABLE(of, aa536_of_match);

static struct mipi_dsi_driver aa536_driver = {
	.probe = aa536_probe,
	.remove = aa536_remove,
	.driver = {
		.name = "panel-oneplus-aa536",
		.of_match_table = aa536_of_match,
	},
};
module_mipi_dsi_driver(aa536_driver);

MODULE_AUTHOR("linux-mdss-dsi-panel-driver-generator");
MODULE_DESCRIPTION("DRM driver for AA536 P 3 A0001 dsc cmd mode panel");
MODULE_LICENSE("GPL");
