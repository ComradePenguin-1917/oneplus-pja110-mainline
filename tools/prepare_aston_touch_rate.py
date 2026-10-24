"""Add a narrow vendor dynamic-rate control to the verified Aston adaptation."""
import difflib
import hashlib
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'out/aston-touch-20261013/verified-ram'
OUT=ROOT/'out/aston-touch-240hz-20261013'
DEST=ROOT/'drivers/input/touchscreen/synaptics-aston-rate'
OUT.mkdir(exist_ok=True);DEST.mkdir(exist_ok=True)
base=json.loads((BASE/'sha256.json').read_text())
records=[]
for name in ('syna_tcm2.c','syna_tcm2.h','syna_tcm2_spi.c','Makefile'):
    raw=(BASE/name).read_bytes()
    assert hashlib.sha256(raw).hexdigest()==base[name]
    original=raw.decode().replace('\r\n','\n');s=original
    if name=='syna_tcm2.c':
        anchor='static int syna_dev_set_up_app_fw(struct syna_tcm *tcm)'
        assert s.count(anchor)==1
        helper='''
/* Rate codes are firmware-specific. Zero preserves the firmware default.
 * Official S3910 controls DC_SET_REPORT_FRE (0xe6) through write_message. */
static unsigned int report_rate_code;
module_param(report_rate_code, uint, 0444);
MODULE_PARM_DESC(report_rate_code, "Verified firmware DC_SET_REPORT_FRE code; 0 leaves default");

static int pja_rate_read(struct tcm_dev *dev, unsigned int *value)
{
    unsigned char id = DC_SET_REPORT_FRE, response;
    int ret = dev->write_message(dev, CMD_GET_DYNAMIC_CONFIG, &id, 1,
                                &response, RESP_IN_POLLING);
    if (ret) return ret;
    if (dev->resp_buf.data_length < 2) return -EPROTO;
    *value = syna_pal_le2_to_uint(dev->resp_buf.buf);
    return 0;
}
static int pja_rate_write(struct tcm_dev *dev, unsigned int value)
{
    unsigned char data[] = { DC_SET_REPORT_FRE, value & 255, value >> 8 }, response;
    unsigned int actual;
    int ret;
    if (value > 9) return -EINVAL;
    ret = dev->write_message(dev, CMD_SET_DYNAMIC_CONFIG, data, sizeof(data),
                            &response, RESP_IN_POLLING);
    if (ret) return ret;
    /* Rate switching may change the firmware report path; reapply the
     * already verified vendor LBP/report setup through the existing core. */
    ret = pja110_configure_lbp(dev);
    if (ret) return ret;
    ret = pja_rate_read(dev, &actual);
    if (ret) return ret;
    return actual == value ? 0 : -EIO;
}
static ssize_t report_rate_code_show(struct device *dev, struct device_attribute *attr, char *buf)
{
    struct syna_tcm *tcm = dev_get_drvdata(dev);
    unsigned int value;
    int ret;
    mutex_lock(&tcm->mutex);
    ret = pja_rate_read(tcm->tcm_dev, &value);
    mutex_unlock(&tcm->mutex);
    return ret ? ret : sysfs_emit(buf, "%u\\n", value);
}
static ssize_t report_rate_code_store(struct device *dev, struct device_attribute *attr,
                                     const char *buf, size_t count)
{
    struct syna_tcm *tcm = dev_get_drvdata(dev);
    unsigned int value;
    int ret = kstrtouint(buf, 0, &value);
    if (ret) return ret;
    mutex_lock(&tcm->mutex);
    ret = pja_rate_write(tcm->tcm_dev, value);
    mutex_unlock(&tcm->mutex);
    return ret ? ret : count;
}
static DEVICE_ATTR_RW(report_rate_code);
static struct attribute *pja_rate_attrs[] = { &dev_attr_report_rate_code.attr, NULL };
ATTRIBUTE_GROUPS(pja_rate);
'''
        s=s.replace(anchor,helper+'\n'+anchor)
        s=s.replace('static irqreturn_t syna_dev_isr(int irq, void *data)', '''
static unsigned int touch_irq_count, touch_parse_errors, touch_read_errors, touch_last_code;
module_param(touch_irq_count, uint, 0444);
module_param(touch_parse_errors, uint, 0444);
module_param(touch_read_errors, uint, 0444);
module_param(touch_last_code, uint, 0444);
static irqreturn_t syna_dev_isr(int irq, void *data)''')
        s=s.replace('\ttcm->isr_pid = current->pid;', '\ttouch_irq_count++;\n\ttcm->isr_pid = current->pid;')
        s=s.replace('''\tif (retval < 0)
\t\tgoto exit;

\tif (code == REPORT_TOUCH) {''', '''\tif (retval < 0) { touch_read_errors++; goto exit; }
\ttouch_last_code = code;

\tif (code == REPORT_TOUCH) {''')
        s=s.replace('''\t\tif (retval < 0)
\t\t\tgoto exit;
\t\tsyna_dev_report_input_events(tcm);''', '''\t\tif (retval < 0) { touch_parse_errors++; goto exit; }
\t\tsyna_dev_report_input_events(tcm);''')
        anchor='\tretval = pja110_configure_lbp(tcm_dev);'
        assert s.count(anchor)==1
        s=s.replace(anchor,anchor+'''
    if (retval) return retval;
    if (report_rate_code) {
        retval = pja_rate_write(tcm_dev, report_rate_code);
        if (retval) return retval;
        pr_info("PJA_ASTON fixed report rate code=%u readback verified\\n", report_rate_code);
    }
''')
        anchor='\t.shutdown = syna_dev_shutdown,'
        assert s.count(anchor)==1
        s=s.replace(anchor,anchor+'\n\t.driver.dev_groups = pja_rate_groups,')
    elif name=='syna_tcm2_spi.c':
        # Active-low ATTN remains asserted while queued reports are unread.
        # At 240Hz a new report may arrive before the previous one is drained;
        # falling-edge-only triggering then permanently loses the wakeup.
        assert s.count('attn->irq_flags = IRQF_TRIGGER_FALLING;')==1
        s=s.replace('attn->irq_flags = IRQF_TRIGGER_FALLING;',
                    'attn->irq_flags = IRQF_TRIGGER_LOW;')
    (DEST/name).write_text(s)
    (OUT/(name+'.patch')).write_text(''.join(difflib.unified_diff(original.splitlines(True),s.splitlines(True),fromfile='verified-ram/'+name,tofile='rate/'+name)))
    if name!='Makefile':records.append({'path':name,'verified_base_sha256':base[name],
        'adapted_sha256':hashlib.sha256((DEST/name).read_bytes()).hexdigest()})
(OUT/'source-manifest.json').write_text(json.dumps({'source_directory':'drivers/input/touchscreen/synaptics-aston-rate',
    'files':records,'default_preserves_firmware_rate':True,'persistent_touch_firmware_changes':False},indent=2)+'\n')
print('Prepared vendor rate read/write on verified Aston TCM; default unchanged')
