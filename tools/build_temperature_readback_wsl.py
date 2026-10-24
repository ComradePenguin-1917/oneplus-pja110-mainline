"""Reuse factory BCC read buffer to inspect matched temperature; no SET."""
from pathlib import Path
import subprocess
import hashlib
import json
win = Path('/mnt/h/workspace/PJA110-Mainline')
root = Path.home() / 'workspace/PJA110-Mainline/charger-native-a'
tree = root / 'linux-6.14'
build = root / 'temperature-readback'
out = win / 'out/native-install-20261017/temperature-readback'
out.mkdir(exist_ok=True)
build.mkdir(exist_ok=True)
s = (win / 'out/native-install-20261017/temperature-handoff/qcom_battmgr-temperature.c').read_text()
s = s.replace('#include "pja110-ap-gauge.h"\n', '')
start = s.index('static int pja110_match_temp')
end = s.index('#define BATTMGR_CHEMISTRY_LEN', start)
s = s[:start] + '''static int readback_result = -EINPROGRESS;
module_param(readback_result, int, 0444);
static int matched_temp = -10000;
module_param(matched_temp, int, 0444);
static bool readback_attempted, readback_pending;
struct pja110_bcc_response {
    struct pmic_glink_hdr hdr;
    __le32 data[128];
    __le32 data_size;
};
#include <linux/soc/qcom/smem.h>
#include <linux/unaligned.h>

''' + s[end:]
needle = '\topcode = le32_to_cpu(hdr->opcode);\n'
pos = s.index(needle, s.index('static void qcom_battmgr_callback')) + len(needle)
s = s[:pos] + '''    if (READ_ONCE(readback_pending)) {
        const struct pja110_bcc_response *bcc = data;
        if (opcode != 0x10003)
            return;
        dev_info(battmgr->dev,
                 "PJA110 BCC response: len=%zu owner=%u type=%u size=%u\\n",
                 len, le32_to_cpu(hdr->owner), le32_to_cpu(hdr->type),
                 len >= sizeof(*bcc) ? le32_to_cpu(bcc->data_size) : 0);
        battmgr->error = -ENODATA;
        if (len == sizeof(*bcc) &&
            le32_to_cpu(hdr->owner) == PMIC_GLINK_OWNER_BATTMGR &&
            le32_to_cpu(hdr->type) == PMIC_GLINK_REQ_RESP &&
            le32_to_cpu(bcc->data_size) >= 32 &&
            le32_to_cpu(bcc->data_size) <= sizeof(bcc->data)) {
            matched_temp = (s32)le32_to_cpu(bcc->data[7]);
            battmgr->error = 0;
        }
        complete(&battmgr->ack);
        return;
    }
''' + s[pos:]
start = s.index('/* One-shot property 29')
end = s.index('static void qcom_battmgr_enable_worker', start)
s = s[:start] + '''/* Factory bcc_read_buffer request. No property SET is issued. */
static int qcom_battmgr_pja110_init(struct qcom_battmgr *b)
{
    struct {
        struct pmic_glink_hdr hdr;
        __le32 data_size;
    } req = {
        .hdr.owner = cpu_to_le32(PMIC_GLINK_OWNER_BATTMGR),
        .hdr.type = cpu_to_le32(PMIC_GLINK_REQ_RESP),
        .hdr.opcode = cpu_to_le32(0x10003),
        .data_size = cpu_to_le32(512),
    };
    const void *project;
    size_t size;
    int ret = -ENODEV;
    if (readback_attempted)
        return 0;
    readback_attempted = true;
    if (!of_machine_is_compatible("oneplus,xigua"))
        goto done;
    project = qcom_smem_get(QCOM_SMEM_HOST_ANY, 135, &size);
    if (IS_ERR(project)) {
        ret = PTR_ERR(project);
        goto done;
    }
    if (size < 8 || get_unaligned_le32((const u8 *)project + 4) != 22851)
        goto done;
    WRITE_ONCE(readback_pending, true);
    ret = qcom_battmgr_request(b, &req, sizeof(req));
    WRITE_ONCE(readback_pending, false);
done:
    WRITE_ONCE(readback_result, ret);
    dev_info(b->dev, "PJA110 BCC matched-temp readback: dC=%d result=%d\\n",
             matched_temp, ret);
    return ret;
}

''' + s[end:]
# The generic upstream-compatible request helper remains, but no SET call site exists.
assert '29, pja110_match_temp' not in s
(build / 'qcom_battmgr.c').write_text(s)
(build / 'pja110-ap-gauge.h').write_bytes((win / 'drivers/power/supply/pja110-ap-gauge.h').read_bytes())
(build / 'Makefile').write_text('obj-m += qcom_battmgr.o\n')
p = subprocess.run(['make', '-C', str(tree), 'ARCH=arm64',
    'CROSS_COMPILE=/opt/aarch64-linux-gnu-toolchain-13.3/bin/aarch64-none-linux-gnu-',
    'M=' + str(build), 'modules'], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
(out / 'build.log').write_bytes(p.stdout)
print(p.stdout.decode(errors='replace'))
p.check_returncode()
data = (build / 'qcom_battmgr.ko').read_bytes()
(out / 'qcom_battmgr-readback.ko').write_bytes(data)
(out / 'qcom_battmgr-readback.c').write_text(s)
(out / 'build-result.json').write_text(json.dumps(dict(strict_link_passed=True,
    sha256=hashlib.sha256(data).hexdigest(), opcode='0x10003', sets_issued=False,
    runtime_verified=False), indent=2) + '\n')
