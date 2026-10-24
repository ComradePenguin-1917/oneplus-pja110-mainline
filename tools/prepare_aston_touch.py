"""Adapt pinned Aston TCM; preserve existing protocol/parser, export exact diffs."""
import difflib
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / 'out/display-touch-reuse-20261013'
SOURCE = AUDIT / 'aston/drivers/input/touchscreen'
OUT = ROOT / 'out/aston-touch-20261013'
DEST = ROOT / 'drivers/input/touchscreen/synaptics-aston'
OUT.mkdir(exist_ok=True)
DEST.mkdir(exist_ok=True)
inventory = json.loads((AUDIT / 'aston-inventory.json').read_text())
blobs = {x['path']: x['sha'] for x in inventory['files']}

def replace(s, old, new, count=1):
    assert s.count(old) == count, (old[:100], s.count(old), count)
    return s.replace(old, new)

def function(s, name, new):
    import re
    m = re.search(r'^(?:static )?(?:int|void) ' + name + r'\([^\n]*(?:\n[^\{]*)?\{', s, re.M)
    assert m, name
    start = m.start()
    brace = s.index('{', m.start())
    depth = 1
    end = brace + 1
    while depth:
        if s[end] == '{': depth += 1
        if s[end] == '}': depth -= 1
        end += 1
    return s[:start] + new.strip() + s[end:]

records = []
for name in ('syna_tcm2.c', 'syna_tcm2.h', 'syna_tcm2_spi.c'):
    data = (SOURCE / name).read_bytes()
    blob = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
    assert blob == blobs['drivers/input/touchscreen/' + name]
    original = data.decode()
    s = original
    if name == 'syna_tcm2.h':
        s = replace(s, '#define TOUCH_INPUT_NAME "touchpanel"',
                    '#define TOUCH_INPUT_NAME "PJA110 Synaptics S3910 (Aston TCM)"')
    elif name == 'syna_tcm2.c':
        s = replace(s, 'for (idx = 0; idx < MAX_NUM_OBJECTS; idx++)',
                    'for (idx = 0; idx < tcm->tcm_dev->max_objects; idx++)')
        s = replace(s, 'input_dev->id.product = SYNAPTICS_TCM_DRIVER_ID;',
                    'input_dev->id.bustype = BUS_SPI;\n\tinput_dev->id.product = SYNAPTICS_TCM_DRIVER_ID;')
        s = replace(s, 'input_mt_init_slots(input_dev, tcm_dev->max_objects, INPUT_MT_DIRECT);',
                    'retval = input_mt_init_slots(input_dev, tcm_dev->max_objects, INPUT_MT_DIRECT);\n'
                    '\tif (retval) { input_free_device(input_dev); return retval; }')
        s = replace(s, '\t\t*data = 0;\n\t\treturn 0;', '\t\treturn -EPROTO;')
        begin = s.index('int syna_tcm_parse_touch_report(')
        end = s.index('static irqreturn_t syna_dev_isr(', begin)
        parser = s[begin:end]
        parser = parser.replace('bits = config_data[idx++];',
            'if (idx >= config_size) return -EPROTO;\n\t\t\tbits = config_data[idx++];')
        parser = parser.replace('obj = data;',
            'if (data >= tcm_dev->max_objects || data >= MAX_NUM_OBJECTS) return -EPROTO;\n\t\t\tobj = data;')
        parser = parser.replace('\t\t\tobject_data[obj].',
            '\t\t\tif (obj >= tcm_dev->max_objects || obj >= MAX_NUM_OBJECTS) return -EPROTO;\n\t\t\tobject_data[obj].')
        s = s[:begin] + parser + s[end:]
        s = replace(s, '\tattn->irq_id = gpio_to_irq(attn->irq_gpio);',
                    '\tattn->irq_id = gpio_to_irq(attn->irq_gpio);\n\tif (attn->irq_id < 0) return attn->irq_id;')
        s = replace(s, '\tcopy_size = MIN(sizeof(tcm_dev->app_info), resp_data_len);',
                    '\t/* S3910 replies with 46 bytes; optional force fields may be absent. */\n'
                    '\tif (resp_data_len < offsetof(struct tcm_application_info, has_hybrid_data) + 2) return -EPROTO;\n'
                    '\tcopy_size = MIN(sizeof(tcm_dev->app_info), resp_data_len);')
        s = replace(s, '\ttcm_dev->max_y = syna_pal_le2_to_uint(info->max_y);',
                    '\ttcm_dev->max_y = syna_pal_le2_to_uint(info->max_y);\n'
                    '\tif (!tcm_dev->max_x || !tcm_dev->max_y || !tcm_dev->max_objects ||\n'
                    '\t    tcm_dev->max_objects > MAX_NUM_OBJECTS) return -EINVAL;')
        s = replace(s, '\tif (tcm->dts_max_x && tcm->dts_max_y) {\n\t\ttcm->firmware_max_x = tcm_dev->max_x;',
                    '\ttcm->firmware_max_x = tcm_dev->max_x;\n\ttcm->firmware_max_y = tcm_dev->max_y;\n'
                    '\tif (!tcm->dts_max_x) tcm->dts_max_x = tcm_dev->max_x;\n'
                    '\tif (!tcm->dts_max_y) tcm->dts_max_y = tcm_dev->max_y;\n'
                    '\tif (tcm->dts_max_x && tcm->dts_max_y) {\n\t\ttcm->firmware_max_x = tcm_dev->max_x;')
        helper = '''
/* PJA110: reuse vendor DC_CONTROL_LBP_HBP=2 and validated volatile layout.
 * The pinned Aston write_message and report interpreter perform all IO/parsing.
 * No reflash, commit or firmware download is added. */
static int pja110_configure_lbp(struct tcm_dev *dev)
{
    unsigned char report = REPORT_TOUCH, response;
    unsigned char lbp[] = { 0x11, 2, 0 };
    const unsigned char config[] = { 2, 6, 4, 7, 4, 8, 16, 9, 16, 3, 0 };
    unsigned int size = syna_pal_le2_to_uint(dev->app_info.max_touch_report_config_size);
    unsigned char *padded;
    int ret;
    if (size < sizeof(config) || size > 256) return -EINVAL;
    ret = dev->write_message(dev, CMD_DISABLE_REPORT, &report, 1, &response, RESP_IN_POLLING);
    if (ret) return ret;
    ret = dev->write_message(dev, CMD_SET_DYNAMIC_CONFIG, lbp, sizeof(lbp), &response, RESP_IN_POLLING);
    if (ret) return ret;
    padded = kzalloc(size, GFP_KERNEL);
    if (!padded) return -ENOMEM;
    memcpy(padded, config, sizeof(config));
    ret = dev->write_message(dev, CMD_SET_TOUCH_REPORT_CONFIG, padded, size, &response, RESP_IN_POLLING);
    kfree(padded);
    if (ret) return ret;
    ret = syna_tcm_preserve_touch_report_config(dev);
    if (ret) return ret;
    if (dev->touch_config.data_length < sizeof(config) ||
        memcmp(dev->touch_config.buf, config, sizeof(config))) return -EPROTO;
    ret = dev->write_message(dev, CMD_ENABLE_REPORT, &report, 1, &response, RESP_IN_POLLING);
    if (!ret) pr_info("PJA_ASTON LBP=2 config readback verified max=%u,%u slots=%u\\n",
                     dev->max_x, dev->max_y, dev->max_objects);
    return ret;
}
'''
        s = replace(s, 'static int syna_dev_set_up_app_fw(struct syna_tcm *tcm)',
                    helper + '\nstatic int syna_dev_set_up_app_fw(struct syna_tcm *tcm)')
        s = replace(s, '\tretval = syna_tcm_preserve_touch_report_config(tcm_dev);',
                    '\tretval = pja110_configure_lbp(tcm_dev);')
        s = replace(s, '\tcancel_delayed_work_sync(&tcm->reflash_work);',
                    '\t/* Reflash was removed by Aston; no uninitialized work to cancel. */')
        s = replace(s, '\t\tif (ret)\n\t\t\treturn -EINVAL;\n\t}\n\n\tsyna_dev_release_input_device(tcm);',
                    '\t\tif (ret) pr_warn("PJA_ASTON reset on disconnect failed: %d\\n", ret);\n'
                    '\t}\n\n\tsyna_dev_release_input_device(tcm);')
        s = replace(s, '\t\tretval = syna_dev_set_up_app_fw(tcm);\n\t\tif (retval >= 0) {',
                    '\t\tretval = syna_dev_set_up_app_fw(tcm);\n\t\tif (retval < 0) goto err_setup_input_dev;\n\t\tif (retval >= 0) {')
        s = replace(s, '\tdefault:\n\t\tbreak;\n\t}\n\n\tretval = syna_dev_request_irq(tcm);',
                    '\tdefault:\n\t\tretval = -ENODEV;\n\t\tgoto err_detect_dev;\n\t}\n\n\tretval = syna_dev_request_irq(tcm);')
        s = replace(s, 'static int syna_dev_probe(struct platform_device *pdev)',
                    'void syna_tcm_remove_device(struct tcm_dev *tcm_dev);\n\nstatic int syna_dev_probe(struct platform_device *pdev)')
        s = replace(s, '\t\tmutex_destroy(&tcm->mutex);\n\t\tgoto err_connect;', '\t\tgoto err_connect;')
        s = replace(s, '\ttcm->speedup_resume_wq = create_singlethread_workqueue("sp_resume0");',
                    '\ttcm->speedup_resume_wq = create_singlethread_workqueue("sp_resume0");\n'
                    '\tif (!tcm->speedup_resume_wq) { retval = -ENOMEM; tcm->dev_disconnect(tcm); goto err_connect; }')
        s = replace(s, '\tmutex_destroy(&tcm->mutex);\nerr_allocate_cdev:',
                    '\tmutex_destroy(&tcm->mutex);\nerr_allocate_cdev:\n'
                    '\tif (tcm_dev) syna_tcm_remove_device(tcm_dev);')
        s = replace(s, '\tmsleep(25);\n\ttcm->driver_current_state = IS_REMOVE;',
                    '\ttcm->driver_current_state = IS_REMOVE;\n'
                    '\tif (tcm->speedup_resume_wq) {\n'
                    '\t\tcancel_work_sync(&tcm->speed_up_work);\n'
                    '\t\tdestroy_workqueue(tcm->speedup_resume_wq);\n\t}')
        s = replace(s, '\treturn platform_driver_register(&syna_dev_driver);',
                    '\tretval = platform_driver_register(&syna_dev_driver);\n'
                    '\tif (retval) syna_hw_interface_exit();\n\treturn retval;')
        s = function(s, 'syna_dev_shutdown', '''
static void syna_dev_shutdown(struct platform_device *pdev)
{
    struct syna_tcm *tcm = platform_get_drvdata(pdev);
    if (tcm->speedup_resume_wq) cancel_work_sync(&tcm->speed_up_work);
    tcm->dev_disconnect(tcm);
}
''')
    else:
        s = replace(s, 'retval = gpio_request(gpio, label);', 'retval = devm_gpio_request(dev, gpio, label);')
        s = replace(s, '\t\tgpio_free(gpio);', '\t\t/* Parent SPI devres releases GPIO after child disconnect. */')
        s = replace(s, 'regulator_get(dev, "vdd")', 'devm_regulator_get(dev, "vdd")')
        s = replace(s, '\t\tregulator_put(pwr->vdd_reg_dev);', '\t\t/* Managed by parent SPI device. */')
        s = function(s, 'syna_spi_config_psu', '''
static int syna_spi_config_psu(struct syna_hw_interface *hw_if)
{
    struct syna_hw_pwr_data *pwr = &hw_if->bdata_pwr;
    struct device *dev = syna_request_managed_device();
    int ret;
    ret = devm_gpio_request_one(dev, pwr->avdd_gpio, GPIOF_OUT_INIT_LOW, "tcm_avdd");
    if (ret) return ret;
    return syna_spi_get_regulator(hw_if, true);
}
''')
        s = function(s, 'syna_spi_power_on', '''
static int syna_spi_power_on(struct syna_hw_interface *hw_if, bool en)
{
    int ret;
    if (en) {
        ret = syna_spi_enable_regulator(hw_if, true);
        if (ret) return ret;
        ret = syna_spi_enable_pwr_gpio(hw_if, true);
        if (ret) { syna_spi_enable_regulator(hw_if, false); return ret; }
        msleep(hw_if->bdata_pwr.power_on_delay_ms);
        return 0;
    }
    ret = syna_spi_enable_pwr_gpio(hw_if, false);
    syna_spi_enable_regulator(hw_if, false);
    return ret;
}
''')
        # Accept the already-verified DT for RAM A/B comparison; no OF mutation.
        for old, new in [('synaptics,irq-gpio', 'attn-gpios'),
                         ('synaptics,reset-gpio', 'reset-gpios'),
                         ('synaptics,avdd-gpio', 'avdd-gpios')]:
            s = s.replace(f'prop = of_find_property(np, "{old}", NULL);',
                f'prop = of_find_property(np, "{old}", NULL);\n'
                f'\tif (!prop) prop = of_find_property(np, "{new}", NULL);')
            s = s.replace(f'of_get_named_gpio(np, "{old}", 0)', 'of_get_named_gpio(np, prop->name, 0)')
        s = replace(s, '\tattn->irq_on_state = 0;',
                    '\tif (attn->irq_gpio < 0 || pwr->avdd_gpio < 0) return -EINVAL;\n'
                    '\tattn->irq_on_state = 0;\n\tattn->irq_flags = IRQF_TRIGGER_FALLING;\n'
                    '\tattn->irq_id = 0;\n\tattn->irq_enabled = false;\n\tpwr->vdd_gpio = -1;')
        # avdd parsing occurs after irq-on-state: validate GPIOs after all parsing.
        s = s.replace('\tif (attn->irq_gpio < 0 || pwr->avdd_gpio < 0) return -EINVAL;\n', '')
        s = replace(s, '\trst->reset_on_state = 0;',
                    '\tif (attn->irq_gpio < 0) return attn->irq_gpio;\n'
                    '\tif (pwr->avdd_gpio < 0) return pwr->avdd_gpio;\n'
                    '\tif (rst->reset_gpio < 0) return rst->reset_gpio;\n\trst->reset_on_state = 0;')
        s = replace(s, '\tsyna_spi_parse_dt(&syna_spi_hw_if, &spi->dev);',
                    '\tretval = syna_spi_parse_dt(&syna_spi_hw_if, &spi->dev);\n'
                    '\tif (retval) goto err_put_device;')
        a = s.index('static int syna_spi_probe(')
        b = s.index('static void syna_spi_remove(', a)
        probe = s[a:b].replace('\t\treturn retval;', '\t\tgoto err_put_device;')
        probe = probe.replace('\treturn 0;\n}', '\treturn 0;\nerr_put_device:\n'
                    '\tsyna_spi_device->dev.platform_data = NULL;\n'
                    '\tplatform_device_put(syna_spi_device);\n\tsyna_spi_device = NULL;\n\treturn retval;\n}')
        s = s[:a] + probe + s[b:]
        s = function(s, 'syna_spi_remove', '''
static void syna_spi_remove(struct spi_device *spi)
{
    /* Child disconnect needs platform_data, but release must not free this
     * static hardware interface. Delete first, then clear borrowed data. */
    platform_device_del(syna_spi_device);
    syna_spi_device->dev.platform_data = NULL;
    platform_device_put(syna_spi_device);
    syna_spi_device = NULL;
    /* All parent resources remain valid until child's disconnect completes. */
    syna_spi_hw_if.bdata_pwr.vdd_reg_dev = NULL;
    /* Parent devres now releases GPIO and regulator handles. */
}
''')
        s = replace(s, '\t{\n\t\t.compatible = "synaptics,tcm-spi-hbp",',
                    '\t{ .compatible = "oneplus,pja110-s3910-probe" },\n\t{\n\t\t.compatible = "synaptics,tcm-spi-hbp",')
        # Free IO buffers only after all SPI callbacks and IRQs have stopped.
        s = replace(s, 'void syna_hw_interface_exit(void)\n{',
                    'void syna_hw_interface_exit(void)\n{\n\tspi_unregister_driver(&syna_spi_driver);')
        s = replace(s, '\n\tspi_unregister_driver(&syna_spi_driver);\n}', '\n}')
    (DEST / name).write_text(s)
    (OUT / (name + '.patch')).write_text(''.join(difflib.unified_diff(
        original.splitlines(True), s.splitlines(True), fromfile='aston/' + name, tofile='pja110/' + name)))
    records.append({'path': name, 'original_blob': blob,
                    'adapted_sha256': hashlib.sha256((DEST / name).read_bytes()).hexdigest()})
(DEST / 'Makefile').write_text('obj-m := synaptics-aston.o\nsynaptics-aston-y := syna_tcm2.o syna_tcm2_spi.o\n')
(OUT / 'source-manifest.json').write_text(json.dumps({'repo': inventory['repo'],
    'commit': inventory['commit'], 'existing_protocol_and_parser_retained': True,
    'files': records, 'phone_execution_confirmed': False}, indent=2) + '\n')
print('Prepared pinned Aston TCM adaptation with exact source patches')
