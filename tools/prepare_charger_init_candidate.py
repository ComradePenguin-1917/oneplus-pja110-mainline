"""Create an opt-in PJA110 charger init patch from mainline qcom_battmgr."""
from pathlib import Path
import difflib

root = Path(__file__).resolve().parents[1]
source = root / 'out/battery-bringup-20261016/charger-source/qcom_battmgr.c'
out = root / 'drivers/power/supply'
out.mkdir(parents=True, exist_ok=True)
s = source.read_text(encoding='utf-8-sig')
original = s
s = s.replace('#include <linux/of_device.h>', '#include <linux/of_device.h>\n#include <linux/of.h>')

def edit(old, new):
    global s
    old = old.replace('\\\\n', '__C_NEWLINE__').replace('\\t', '\t').replace('\\n', '\n').replace('__C_NEWLINE__', '\\n')
    new = new.replace('\\t', '\t')
    if old == '\treturn qcom_battmgr_request(battmgr, &request, sizeof(request));\n}':
        old += '\n\nstatic int qcom_battmgr_update_status'
        new += '\n\nstatic int qcom_battmgr_update_status'
    if s.count(old) != 1 and 'failed to request power notifications' in old:
        start = s.index(chr(9) + 'ret = qcom_battmgr_request(battmgr, &req, sizeof(req));')
        end = s.index(';', s.index('failed to request power notifications', start)) + 1
        old = s[start:end]
    assert s.count(old) == 1, repr(old[:150])
    s = s.replace(old, new)

edit('#define BATTMGR_CHEMISTRY_LEN', '''static bool pja110_charger_init;
module_param(pja110_charger_init, bool, 0400);
MODULE_PARM_DESC(pja110_charger_init, "Opt in to PJA110 OEM 500mA charger initialization");
#define BATT_CHG_EN 24

#define BATTMGR_CHEMISTRY_LEN''')
edit('\tint error;\n', '\tint error;\n\tu32 pending_set_opcode;\n\tu32 pending_set_property;\n')
edit('\treturn qcom_battmgr_request(battmgr, &request, sizeof(request));\n}', '''\tWRITE_ONCE(battmgr->pending_set_property, property);
\tWRITE_ONCE(battmgr->pending_set_opcode,
\t\t   opcode == BATTMGR_BAT_PROPERTY_SET ||
\t\t   opcode == BATTMGR_USB_PROPERTY_SET ? opcode : 0);
\t{
\t\tint ret = qcom_battmgr_request(battmgr, &request, sizeof(request));
\t\tWRITE_ONCE(battmgr->pending_set_opcode, 0);
\t\treturn ret;
\t}
}''')
edit('\tunsigned int opcode = le32_to_cpu(hdr->opcode);\n\n\tif (opcode == BATTMGR_NOTIFICATION)', '''\tunsigned int opcode;
\tconst struct qcom_battmgr_message *resp = data;

\tif (len < sizeof(*hdr))
\t\treturn;
\topcode = le32_to_cpu(hdr->opcode);
\tif (READ_ONCE(battmgr->pending_set_opcode)) {
\t\tif (opcode != READ_ONCE(battmgr->pending_set_opcode) ||
\t\t    len != sizeof(*hdr) + sizeof(resp->intval) ||
\t\t    le32_to_cpu(hdr->type) != PMIC_GLINK_REQ_RESP ||
\t\t    le32_to_cpu(resp->intval.property) != battmgr->pending_set_property)
\t\t\treturn;
\t\tbattmgr->error = le32_to_cpu(resp->intval.result) ? -EREMOTEIO : 0;
\t\tcomplete(&battmgr->ack);
\t\treturn;
\t}
\tif (opcode == BATTMGR_BAT_PROPERTY_SET || opcode == BATTMGR_USB_PROPERTY_SET)
\t\treturn;

\tif (opcode == BATTMGR_NOTIFICATION)''')

point = 'static void qcom_battmgr_enable_worker(struct work_struct *work)'
helper = r'''/* Gated downstream initialization adapted from oplus_chg_hw_init. */
static int qcom_battmgr_pja110_init(struct qcom_battmgr *b)
{
\tint ret;

\tif (!pja110_charger_init || !of_machine_is_compatible("oneplus,xigua"))
\t\treturn 0;
\tif (b->variant != QCOM_BATTMGR_SM8350 || !b->service_up)
\t\treturn -ENODEV;
\tret = qcom_battmgr_request_property(b, BATTMGR_USB_PROPERTY_GET, USB_ONLINE, 0);
\tif (ret || !b->usb.online)
\t\treturn ret ? ret : -ENOLINK;
\tret = qcom_battmgr_request_property(b, BATTMGR_BAT_PROPERTY_GET, BATT_PRESENT, 0);
\tif (ret || !b->info.present)
\t\treturn ret ? ret : -ENODEV;
\tret = qcom_battmgr_request_property(b, BATTMGR_BAT_PROPERTY_GET, BATT_HEALTH, 0);
\tif (ret || b->status.health != POWER_SUPPLY_HEALTH_GOOD)
\t\treturn ret ? ret : -EPERM;
\tret = qcom_battmgr_request_property(b, BATTMGR_BAT_PROPERTY_GET, BATT_TEMP, 0);
\tif (ret || (int)b->status.temperature < 100 || b->status.temperature > 400)
\t\treturn ret ? ret : -ERANGE;
\tret = qcom_battmgr_request_property(b, BATTMGR_USB_PROPERTY_GET, USB_CURR_MAX, 0);
\tif (ret || b->usb.current_max < 500000)
\t\treturn ret ? ret : -ERANGE;
\t/* UINT_MAX is the documented OEM unsuspend sentinel, not an ICL. */
\tret = qcom_battmgr_request_property(b, BATTMGR_USB_PROPERTY_SET,
\t\t\t\t\t     USB_INPUT_CURR_LIMIT, U32_MAX);
\tdev_info(b->dev, "PJA110 unsuspend response: %d\\n", ret);
\tif (ret)
\t\treturn ret;
\tret = qcom_battmgr_request_property(b, BATTMGR_USB_PROPERTY_SET,
\t\t\t\t\t     USB_INPUT_CURR_LIMIT, 500000);
\tdev_info(b->dev, "PJA110 500mA vote response: %d\\n", ret);
\tif (ret)
\t\treturn ret;
\tret = qcom_battmgr_request_property(b, BATTMGR_BAT_PROPERTY_SET,
\t\t\t\t\t     BATT_CHG_EN, 1);
\tdev_info(b->dev, "PJA110 charge-enable response: %d\\n", ret);
\treturn ret;
}

'''.replace('\\t', '\t')
edit(point, helper + point)
edit('\tret = qcom_battmgr_request(battmgr, &req, sizeof(req));\n\tif (ret)\n\t\tdev_err(battmgr->dev, "failed to request power notifications\\n");', '''\tmutex_lock(&battmgr->lock);
\tret = qcom_battmgr_request(battmgr, &req, sizeof(req));
\tif (!ret)
\t\tret = qcom_battmgr_pja110_init(battmgr);
\tmutex_unlock(&battmgr->lock);
\tif (ret)
\t\tdev_err(battmgr->dev, "notification/charger initialization stopped: %d\\n", ret);''')

edit('\tint error;\n', '\tint error;\n\tbool request_failed;\n')
edit('\treinit_completion(&battmgr->ack);', '''\t/* After a failed transaction, late replies are ambiguous. Reprobe first. */
\tif (READ_ONCE(battmgr->request_failed))
\t\treturn -EIO;
\treinit_completion(&battmgr->ack);''')
edit('\tif (ret < 0)\n\t\treturn ret;\n\n\tleft = wait_for_completion_timeout', '''\tif (ret < 0) {
\t\tWRITE_ONCE(battmgr->request_failed, true);
\t\treturn ret;
\t}

\tleft = wait_for_completion_timeout''')
edit('\tif (!left)\n\t\treturn -ETIMEDOUT;', '''\tif (!left) {
\t\tWRITE_ONCE(battmgr->request_failed, true);
\t\treturn -ETIMEDOUT;
\t}''')
edit('static int qcom_battmgr_probe(struct auxiliary_device *adev,', '''static void qcom_battmgr_cancel_work(void *data)
{
\tstruct qcom_battmgr *b = data;

\tcancel_work_sync(&b->enable_work);
}

static int qcom_battmgr_probe(struct auxiliary_device *adev,''')
edit('\tstruct device *dev = &adev->dev;', '\tstruct device *dev = &adev->dev;\n\tint ret;')
edit('\tpmic_glink_client_register(battmgr->client);', '''\tret = devm_add_action_or_reset(dev, qcom_battmgr_cancel_work, battmgr);
\tif (ret)
\t\treturn ret;
\tpmic_glink_client_register(battmgr->client);''')
cleanup = '\tret = devm_add_action_or_reset(dev, qcom_battmgr_cancel_work, battmgr);\n\tif (ret)\n\t\treturn ret;\n'
gate = '\t/* UINT_MAX is the documented OEM unsuspend sentinel, not an ICL. */'
assert s.count(gate) == 1
# The OEM board uses an AP-owned gauge; ADSP battery defaults are not a gate.
start = s.index(chr(9) + 'ret = qcom_battmgr_request_property(b, BATTMGR_BAT_PROPERTY_GET, BATT_PRESENT, 0);')
end = s.index(chr(9) + 'ret = qcom_battmgr_request_property(b, BATTMGR_USB_PROPERTY_GET, USB_CURR_MAX, 0);', start)
s = s[:start] + '\tret = pja110_ap_gauge_check(b->dev);\n\tif (ret)\n\t\treturn ret;\n' + s[end:]
s = s.replace('/* Gated downstream initialization adapted from oplus_chg_hw_init. */', '#include "pja110-ap-gauge.h"\n\n/* Gated downstream initialization adapted from oplus_chg_hw_init. */')
assert s.count(cleanup) == 1
s = s.replace(cleanup, '')
allocation = '\tbattmgr->client = devm_pmic_glink_client_alloc('
assert s.count(allocation) == 1
s = s.replace(allocation, cleanup + '\n' + allocation)
s = s.replace(chr(92) + chr(92) + 'n', chr(92) + 'n')
(out / 'qcom_battmgr.c').write_bytes(s.encode())
(out / 'Makefile').write_bytes(b'obj-m += qcom_battmgr.o' + bytes([10]))
diff = difflib.unified_diff(original.splitlines(True), s.splitlines(True),
                            fromfile='a/drivers/power/supply/qcom_battmgr.c',
                            tofile='b/drivers/power/supply/qcom_battmgr.c')
(out / 'pja110-init.patch').write_bytes(''.join(diff).encode())
print('Created opt-in patch. No phone state or charging control changed.')

