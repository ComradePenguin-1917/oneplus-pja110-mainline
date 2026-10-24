// SPDX-License-Identifier: GPL-2.0-only
/* PJA110 S3910 transport bring-up. No firmware download or flash commands. */
#include <linux/delay.h>
#include <linux/gpio/consumer.h>
#include <linux/input/mt.h>
#include <linux/interrupt.h>
#include <linux/module.h>
#include <linux/regulator/consumer.h>
#include <linux/spi/spi.h>

struct pja_touch {
	struct spi_device *spi;
	struct gpio_desc *reset, *avdd, *attn;
	struct regulator *vdd;
	struct input_dev *input;
	u8 *message;
	unsigned int max_x, max_y, objects;
};

static bool enable_touch;
module_param(enable_touch, bool, 0444);
MODULE_PARM_DESC(enable_touch, "Enable volatile standard touch reporting after verified identification");

static void pja_touch_poweroff(void *data)
{
	struct pja_touch *t = data;
	gpiod_set_value_cansleep(t->reset, 1);
	gpiod_set_value_cansleep(t->avdd, 0);
	regulator_disable(t->vdd);
}

static int pja_touch_read(struct pja_touch *t, u8 *data, size_t len)
{
	u8 *dummy;
	struct spi_transfer xfer = { .rx_buf = data, .len = len };
	int ret;
	dummy = kmalloc(len, GFP_KERNEL);
	if (!dummy)
		return -ENOMEM;
	memset(dummy, 0xff, len);
	xfer.tx_buf = dummy;
	ret = spi_sync_transfer(t->spi, &xfer, 1);
	kfree(dummy);
	return ret;
}

static int pja_touch_message(struct pja_touch *t, u8 *code)
{
	u8 header[4];
	int ret, len;
	ret = pja_touch_read(t, header, sizeof(header));
	if (ret)
		return ret;
	if (header[0] != 0xa5)
		return -EPROTO;
	*code = header[1];
	len = header[2] | (header[3] << 8);
	if (len > 1024)
		return -EMSGSIZE;
	if (!len)
		return 0;
	ret = pja_touch_read(t, t->message, len + 3);
	if (ret)
		return ret;
	if (t->message[0] != 0xa5 || t->message[1] != 0x03 ||
	    t->message[len + 2] != 0x5a)
		return -EPROTO;
	memmove(t->message, t->message + 2, len);
	return len;
}

/* Only volatile reporting and information commands; never flash or commit. */
static int pja_touch_command(struct pja_touch *t, u8 cmd, const u8 *payload, size_t len)
{
	u8 *packet, code;
	int ret, i;
	if (len > 256)
		return -EMSGSIZE;
	packet = kmalloc(len + 3, GFP_KERNEL);
	if (!packet)
		return -ENOMEM;
	packet[0] = cmd; packet[1] = len; packet[2] = len >> 8;
	if (len)
		memcpy(packet + 3, payload, len);
	ret = spi_write(t->spi, packet, len + 3);
	kfree(packet);
	if (ret)
		return ret;
	for (i = 0; i < 100; i++) {
		msleep(20);
		ret = pja_touch_message(t, &code);
		if (ret < 0)
			return ret;
		if (code == 1) {
			dev_info(&t->spi->dev, "PJA_TOUCH command=%02x OK len=%d\n", cmd, ret);
			return ret;
		}
		if (code > 1 && code < 0x10) {
			dev_err(&t->spi->dev, "PJA_TOUCH command=%02x status=%02x\n", cmd, code);
			return -EIO;
		}
	}
	return -ETIMEDOUT;
}

static int pja_touch_report(struct pja_touch *t, int len)
{
	bool seen[16] = {};
	int i;
	if (len != t->objects * 5)
		return -EPROTO;
	/* Validate the entire packet before changing any slot. */
	for (i = 0; i < t->objects; i++) {
		u8 *p = t->message + i * 5;
		unsigned int slot = p[0] & 15, type = p[0] >> 4;
		unsigned int x = p[1] | (p[2] << 8), y = p[3] | (p[4] << 8);
		if (slot >= t->objects || seen[slot] ||
		    ((type == 1 || type == 2) && (x > t->max_x || y > t->max_y)))
			return -EPROTO;
		seen[slot] = true;
	}
	for (i = 0; i < t->objects; i++) {
		u8 *p = t->message + i * 5;
		unsigned int type = p[0] >> 4;
		bool active = type == 1 || type == 2;
		input_mt_slot(t->input, p[0] & 15);
		input_mt_report_slot_state(t->input, MT_TOOL_FINGER, active);
		if (active) {
			input_report_abs(t->input, ABS_MT_POSITION_X, p[1] | (p[2] << 8));
			input_report_abs(t->input, ABS_MT_POSITION_Y, p[3] | (p[4] << 8));
		}
	}
	input_mt_sync_frame(t->input);
	input_sync(t->input);
	return 0;
}

static irqreturn_t pja_touch_irq(int irq, void *data)
{
	struct pja_touch *t = data;
	u8 code;
	int i, ret;
	for (i = 0; i < 32; i++) {
		ret = pja_touch_message(t, &code);
		if (ret < 0) {
			dev_err_ratelimited(&t->spi->dev, "PJA_TOUCH read failed: %d\n", ret);
			break;
		}
		if (code == 0x11 && pja_touch_report(t, ret))
			dev_err_ratelimited(&t->spi->dev, "PJA_TOUCH invalid touch packet len=%d\n", ret);
		if (gpiod_get_value_cansleep(t->attn) <= 0)
			break;
	}
	return IRQ_HANDLED;
}

static int pja_touch_input(struct pja_touch *t)
{
	struct device *dev = &t->spi->dev;
	/* All objects: slot4/class4/x16/y16 = five bytes per object. */
	const u8 config[] = { 0x02, 0x06, 4, 0x07, 4, 0x08, 16, 0x09, 16, 0x03, 0x00 };
	u8 report = 0x11, lbp[] = { 0x11, 0x02, 0x00 }, *padded;
	int ret, size, irq;
	ret = pja_touch_command(t, 0x20, NULL, 0);
	if (ret < 40)
		return ret < 0 ? ret : -EPROTO;
	dev_info(dev, "PJA_TOUCH app-info=%*ph\n", min(ret, 48), t->message);
	if (t->message[2] || t->message[3])
		return -EBUSY;
	size = t->message[12] | (t->message[13] << 8);
	t->max_x = t->message[32] | (t->message[33] << 8);
	t->max_y = t->message[34] | (t->message[35] << 8);
	t->objects = t->message[36] | (t->message[37] << 8);
	if (size < sizeof(config) || size > 256 || !t->max_x || !t->max_y ||
	    !t->objects || t->objects > 16)
		return -EINVAL;
	ret = pja_touch_command(t, 0x06, &report, 1);
	if (ret < 0)
		return ret;
	ret = pja_touch_command(t, 0x24, lbp, sizeof(lbp));
	if (ret < 0)
		return ret;
	padded = kzalloc(size, GFP_KERNEL);
	if (!padded)
		return -ENOMEM;
	memcpy(padded, config, sizeof(config));
	ret = pja_touch_command(t, 0x26, padded, size);
	kfree(padded);
	if (ret < 0)
		return ret;
	ret = pja_touch_command(t, 0x25, NULL, 0);
	if (ret < 0)
		return ret;
	if (ret < sizeof(config) || memcmp(t->message, config, sizeof(config)))
		return -EPROTO;
	t->input = devm_input_allocate_device(dev);
	if (!t->input)
		return -ENOMEM;
	t->input->name = "PJA110 Synaptics S3910";
	t->input->id.bustype = BUS_SPI;
	input_set_abs_params(t->input, ABS_MT_POSITION_X, 0, t->max_x, 0, 0);
	input_set_abs_params(t->input, ABS_MT_POSITION_Y, 0, t->max_y, 0, 0);
	ret = input_mt_init_slots(t->input, t->objects, INPUT_MT_DIRECT | INPUT_MT_DROP_UNUSED);
	if (ret)
		return ret;
	ret = input_register_device(t->input);
	if (ret)
		return ret;
	ret = pja_touch_command(t, 0x05, &report, 1);
	if (ret < 0)
		return ret;
	irq = gpiod_to_irq(t->attn);
	if (irq < 0)
		return irq;
	ret = devm_request_threaded_irq(dev, irq, NULL, pja_touch_irq,
		IRQF_TRIGGER_FALLING | IRQF_ONESHOT, "pja110-s3910", t);
	if (ret)
		return ret;
	dev_info(dev, "PJA_TOUCH input enabled: max=%u,%u slots=%u irq=%d\n",
		t->max_x, t->max_y, t->objects, irq);
	return 0;
}

static int pja_touch_probe(struct spi_device *spi)
{
	struct device *dev = &spi->dev;
	struct pja_touch *t;
	u8 *buf, magic = 0x07;
	int ret, len;
	t = devm_kzalloc(dev, sizeof(*t), GFP_KERNEL);
	if (!t)
		return -ENOMEM;
	t->spi = spi;
	t->vdd = devm_regulator_get(dev, "vdd");
	if (IS_ERR(t->vdd))
		return dev_err_probe(dev, PTR_ERR(t->vdd), "touch vdd unavailable\n");
#define GET_GPIO(member, flags) \
	t->member = devm_gpiod_get(dev, #member, flags); \
	if (IS_ERR(t->member)) return dev_err_probe(dev, PTR_ERR(t->member), #member " unavailable\n")
	GET_GPIO(reset, GPIOD_OUT_HIGH);
	GET_GPIO(avdd, GPIOD_OUT_LOW);
	GET_GPIO(attn, GPIOD_IN);
#undef GET_GPIO
	ret = regulator_set_voltage(t->vdd, 1800000, 1800000);
	if (ret)
		return ret;
	ret = regulator_enable(t->vdd);
	if (ret)
		return ret;
	ret = devm_add_action_or_reset(dev, pja_touch_poweroff, t);
	if (ret)
		return ret;
	gpiod_set_value_cansleep(t->avdd, 1);
	msleep(200);
	gpiod_set_value_cansleep(t->reset, 1);
	msleep(10);
	gpiod_set_value_cansleep(t->reset, 0);
	msleep(80);
	spi->mode = SPI_MODE_0;
	spi->bits_per_word = 8;
	spi->max_speed_hz = 1000000;
	ret = spi_setup(spi);
	if (ret)
		return ret;
	buf = devm_kmalloc(dev, 1030, GFP_KERNEL);
	if (!buf)
		return -ENOMEM;
	t->message = buf;
	dev_info(dev, "PJA_TOUCH powered; ATTN logical=%d; mode0 1MHz\n",
		 gpiod_get_value_cansleep(t->attn));
	/* Same one-byte discovery magic as vendor syna_tcm_detect_device(). */
	ret = spi_write(spi, &magic, 1);
	if (ret)
		return dev_err_probe(dev, ret, "discovery write failed\n");
	msleep(20);
	ret = pja_touch_read(t, buf, 4);
	if (ret)
		return dev_err_probe(dev, ret, "header read failed\n");
	dev_info(dev, "PJA_TOUCH discovery header=%*ph ATTN=%d\n", 4, buf,
		 gpiod_get_value_cansleep(t->attn));
	if (buf[0] == 0xa5) {
		len = buf[2] | (buf[3] << 8);
		dev_info(dev, "PJA_TOUCH TCMv1 code=%02x payload_len=%d\n", buf[1], len);
		if (len > 0 && len <= 1024) {
			/* Continued marker/status, payload, optional CRC/RC and EOM. */
			ret = pja_touch_read(t, buf, len + 6);
			if (ret)
				return dev_err_probe(dev, ret, "payload read failed\n");
			dev_info(dev, "PJA_TOUCH continued=%*ph\n", min(len + 6, 64), buf);
			if (enable_touch) {
				if (len < 24 || buf[0] != 0xa5 || buf[1] != 0x03 ||
				    buf[3] != 1 || memcmp(buf + len + 2, "\x5a\x5a\x5a\x5a", 4))
					return -EPROTO;
				return pja_touch_input(t);
			}
		}
	}
	if (enable_touch)
		return -EPROTO;
	dev_info(dev, "PJA_TOUCH diagnostic complete; no input device registered yet\n");
	return 0;
}

static const struct of_device_id pja_touch_of[] = {
	{ .compatible = "oneplus,pja110-s3910-probe" }, {}
};
MODULE_DEVICE_TABLE(of, pja_touch_of);
static const struct spi_device_id pja_touch_ids[] = { { "pja110-s3910-probe" }, {} };
MODULE_DEVICE_TABLE(spi, pja_touch_ids);
static struct spi_driver pja_touch_driver = {
	.driver = { .name = "pja110-s3910-probe", .of_match_table = pja_touch_of },
	.probe = pja_touch_probe, .id_table = pja_touch_ids,
};
module_spi_driver(pja_touch_driver);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("PJA110 S3910 bounded transport diagnostic without flash writes");
