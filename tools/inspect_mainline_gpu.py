"""Read-only GPU bring-up inventory; mount stock firmware partition read-only."""
import hashlib
import json
import re
import subprocess
from pathlib import Path
from fdt import FDT

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'out/gpu-inspection-20261014'
OUT.mkdir(exist_ok=True)
KEYS = ROOT / 'out/usb-ncm-20261013/ssh'
SSH = ['C:/Windows/System32/OpenSSH/ssh.exe', '-F', 'none', '-T',
       '-i', str(KEYS/'client_key_host'), '-o', 'BatchMode=yes',
       '-o', 'IdentitiesOnly=yes', '-o', 'StrictHostKeyChecking=yes',
       '-o', f'UserKnownHostsFile={KEYS/"known_hosts"}',
       '-o', 'ConnectTimeout=5', 'root@169.254.42.1']

def read(command):
    p = subprocess.run(SSH+[command], capture_output=True, timeout=60)
    (OUT/'last-stderr.txt').write_bytes(p.stderr)
    p.check_returncode()
    return p.stdout

state=read('uname -a; cat /proc/uptime; ls -l /dev/dri; '
           'ls -l /sys/bus/platform/drivers/adreno /sys/bus/platform/drivers/gpu_cc-sm8550; '
           'dmesg')
(OUT/'device-state.txt').write_bytes(state)
blob=read('cat /sys/firmware/fdt')
(OUT/'live.dtb').write_bytes(blob)
nodes=FDT(blob).nodes()
selected={path:{k:v.hex() for k,v in props.items()} for path,props in nodes.items()
          if any(x in path for x in ('gpu@3d00000','gmu@3d6a000','clock-controller@3d90000','iommu@3da0000','gpu-micro-code-region'))}
(OUT/'gpu-device-tree.json').write_text(json.dumps(selected,indent=2)+'\n')
gpu=nodes['/soc@0/gpu@3d00000']
assert gpu['status']==b'disabled\0'
assert b'no GPU device was found' in state
raw=read('for f in /sys/class/block/sd*/uevent; do cat "$f"; echo END; done').decode()
found=[]
for record in raw.split('END'):
    props=dict(line.split('=',1) for line in record.splitlines() if '=' in line)
    if props.get('PARTNAME')=='modem_a': found.append(props['DEVNAME'])
assert len(found)==1 and re.fullmatch(r'sd[a-z]+[0-9]+',found[0])
dev=found[0]
assert read(f"grep '^PARTNAME=' /sys/class/block/{dev}/uevent").strip()==b'PARTNAME=modem_a'
mount='/tmp/gpu-firmware-inspection'
listing=read(f'''set -e
mkdir -p {mount}
mount -t vfat -o ro /dev/{dev} {mount}
trap 'umount {mount}' EXIT HUP INT TERM
find {mount} -type f | grep -iE 'a740|a730|gmu|zap|sqe' || true
''')
(OUT/'stock-firmware-list.txt').write_bytes(listing)
report={'kernel':state.decode().splitlines()[0], 'gpu_status':'disabled',
        'render_node_alone_is_not_gpu_proof':True,
        'required_firmware':['qcom/a740_sqe.fw','qcom/gmu_gen70200.bin',
                             'qcom/sm8550/xigua/a740_zap.mbn (board DT firmware-name)'],
        'stock_modem_a_gpu_files':listing.decode().splitlines(),
        'live_dtb_sha256':hashlib.sha256(blob).hexdigest(),
        'partitions_written':False}
(OUT/'inspection.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
