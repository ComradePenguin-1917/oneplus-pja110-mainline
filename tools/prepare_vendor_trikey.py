"""Stage pinned OnePlus hall drivers, changing only mainline API compatibility."""
import difflib
import hashlib
import json
import re
import subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
GIT=ROOT/'out/display-baseline-20261013/oneplus-source/git'
SHA='f034653c086942be9398171cfa7477ddbe2d9504'
assert subprocess.check_output(['git','-C',str(GIT),'rev-parse','HEAD']).decode().strip()==SHA
SOURCE=GIT/'vendor/oplus/kernel/device_info/tri_state_key'
OUT=ROOT/'out/buttons-20261013/vendor-trikey'
OUT.mkdir(exist_ok=True)
paths=['oplus_tri_key.c','oplus_tri_key.h','ist_hall_ic/hall_ist8801.h',
       'ist_hall_ic/hall_ist8801_up.c','ist_hall_ic/hall_ist8801_down.c',
       'hall_ic/hall_mxm1120.h','hall_ic/hall_mxm1120_up.c','hall_ic/hall_mxm1120_down.c']
records=[]
for name in paths:
    original=(SOURCE/name).read_text()
    adapted=original
    if name.endswith(('.c','.h')):
        # CONFIG_DRM_MSM means a vendor notifier in this Android source, while
        # mainline uses the same config name without that private API.
        adapted=adapted.replace('CONFIG_DRM_MSM','CONFIG_PJA110_VENDOR_DRM_MSM_NOTIFY')
        adapted=adapted.replace('FB_EARLY_EVENT_BLANK','FB_EVENT_BLANK')
        adapted=adapted.replace('FB_BLANK_BLANK','FB_BLANK_POWERDOWN')
    if name.endswith('.c') and ('ist_hall_ic/' in name or 'hall_ic/' in name):
        adapted=adapted.replace('#include <linux/i2c.h>','#include <linux/i2c.h>\n#include <linux/pinctrl/consumer.h>')
        adapted=re.sub(r'(static int \w+\(struct i2c_client \*client),\s*const struct i2c_device_id \*id\)',r'\1)',adapted)
        adapted=re.sub(r'of_get_named_gpio_flags\(([^;]*?),\s*NULL\)',r'of_get_named_gpio(\1)',adapted)
        adapted=adapted.replace('id->name','client->name')
    target=OUT/name
    target.parent.mkdir(exist_ok=True)
    target.write_text(adapted)
    patch=''.join(difflib.unified_diff(original.splitlines(True),adapted.splitlines(True),fromfile='vendor/'+name,tofile='mainline/'+name))
    (OUT/(name.replace('/','-')+'.patch')).write_text(patch)
    records.append({'path':name,'vendor_sha256':hashlib.sha256((SOURCE/name).read_bytes()).hexdigest(),
                    'adapted_sha256':hashlib.sha256(target.read_bytes()).hexdigest()})
(OUT/'Makefile').write_text('obj-m += oplus_bsp_tri_key.o\noplus_bsp_tri_key-y := oplus_tri_key.o\nobj-m += ist_hall_ic/hall_ist8801_up.o ist_hall_ic/hall_ist8801_down.o\nobj-m += hall_ic/hall_mxm1120_up.o hall_ic/hall_mxm1120_down.o\n')
(OUT/'provenance.json').write_text(json.dumps({'repo':'OnePlusOSS/android_kernel_modules_and_devicetree_oneplus_sm8550',
    'commit':SHA,'source_directory':'vendor/oplus/kernel/device_info/tri_state_key',
    'sensor_and_position_algorithms_reused':True,'files':records,'phone_execution_confirmed':False},indent=2)+'\n')
print('Staged official OnePlus hall sensors and tri-state algorithm, with reviewable API diffs')
