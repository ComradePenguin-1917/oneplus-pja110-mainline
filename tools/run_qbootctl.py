"""Guarded use of upstream qbootctl with snapshots and explicit B selection."""
import hashlib,json,re,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'out/boot-success-20261014'
KEYS=ROOT/'out/usb-ncm-20261013/ssh'
SSH=['C:/Windows/System32/OpenSSH/ssh.exe','-F','none','-T','-i',str(KEYS/'client_key_host'),
 '-o','BatchMode=yes','-o','IdentitiesOnly=yes','-o','StrictHostKeyChecking=yes',
 '-o',f'UserKnownHostsFile={KEYS/"known_hosts"}','-o','ConnectTimeout=5','root@169.254.42.1']
def read(cmd,data=None):
 p=subprocess.run(SSH+[cmd],input=data,capture_output=True,timeout=60)
 (OUT/'last-stderr.txt').write_bytes(p.stderr);p.check_returncode();return p.stdout
raw=read('for f in /sys/class/block/sd*/uevent; do cat "$f"; echo END; done').decode()
parts={};ambiguous=set()
for r in raw.split('END'):
 p=dict(l.split('=',1) for l in r.splitlines() if '=' in l)
 if 'PARTNAME' in p:
  if p['PARTNAME'] in parts:ambiguous.add(p['PARTNAME'])
  assert re.fullmatch(r'sd[a-z]+[0-9]+',p['DEVNAME'])
  assert re.fullmatch(r'[a-zA-Z0-9_-]+',p['PARTNAME'])
  parts[p['PARTNAME']]=p['DEVNAME']
for name in ambiguous:
 assert not name.endswith(('_a','_b')),'ambiguous slot partition'
 del parts[name]
read('mkdir -p /dev/disk/by-partlabel')
for name,dev in parts.items():
 read(f'test ! -e /dev/disk/by-partlabel/{name} || test "$(readlink /dev/disk/by-partlabel/{name})" = /dev/{dev}; ln -sfn /dev/{dev} /dev/disk/by-partlabel/{name}')
binary=(OUT/'qbootctl-aarch64').read_bytes()
assert read('cat > /tmp/qbootctl; chmod 700 /tmp/qbootctl; sha256sum /tmp/qbootctl',binary).decode().split()[0]==hashlib.sha256(binary).hexdigest()
mode=sys.argv[1]
if mode=='probe':
 state=read('/tmp/qbootctl -a; /tmp/qbootctl -n 0; /tmp/qbootctl -n 1; /tmp/qbootctl -b 1')
 (OUT/'qbootctl-before.txt').write_bytes(state);print(state.decode())
elif mode=='mark':
 assert b'Active slot: _b' in (OUT/'qbootctl-before.txt').read_bytes()
 state=read('uname -a; cat /sys/bus/platform/devices/1d84000.ufshc/attributes/boot_lun_enabled; /tmp/qbootctl -a')
 assert b'#18 SMP' in state and b'0x00000002' in state and b'Active slot: _b' in state
 report=json.loads((OUT/'before/gpt.json').read_text())
 for disk in report:
  a,b=disk['copies']
  assert a['header_crc_valid'] and a['table_crc_valid'] and b['header_crc_valid']
  assert a['current_lba']==a['physical_header_lba'] and b['current_lba']==b['physical_header_lba']
  assert a['entries']==b['entries'] or disk['device']=='sde'
  if disk['device']=='sde':
   pa={e['name']:e for e in a['entries']};pb={e['name']:e for e in b['entries']}
   assert set(pa)==set(pb)
   assert [n for n in pa if pa[n]!=pb[n]]==['boot_b']
   aa=pa['boot_b'];bb=pb['boot_b']
   assert not aa['successful'] and aa['active'] and not aa['unbootable'] and aa['retry_count']==6
   assert int(aa['attributes'],16)^int(bb['attributes'],16)==1<<51
   assert {k:v for k,v in aa.items() if k not in ('attributes','ab_byte','retry_count')}=={k:v for k,v in bb.items() if k not in ('attributes','ab_byte','retry_count')}
 state=read('/tmp/qbootctl -m 1; sync; /tmp/qbootctl -n 1; /tmp/qbootctl -n 0; /tmp/qbootctl -a')
 (OUT/'qbootctl-mark.txt').write_bytes(state);print(state.decode())
 assert b'SLOT _b: is marked successful' in state
else:raise SystemExit('probe | mark')
