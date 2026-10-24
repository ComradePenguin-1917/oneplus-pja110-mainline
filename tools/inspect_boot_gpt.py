"""Read-only GPT snapshot with independent header/table CRC validation."""
import json,struct,zlib,subprocess,hashlib,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'out/boot-success-20261014'
DEST=OUT/(sys.argv[1] if len(sys.argv)>1 else 'before');DEST.mkdir(exist_ok=True)
KEYS=ROOT/'out/usb-ncm-20261013/ssh'
SSH=['C:/Windows/System32/OpenSSH/ssh.exe','-F','none','-T','-i',str(KEYS/'client_key_host'),
 '-o','BatchMode=yes','-o','IdentitiesOnly=yes','-o','StrictHostKeyChecking=yes',
 '-o',f'UserKnownHostsFile={KEYS/"known_hosts"}','-o','ConnectTimeout=5','root@169.254.42.1']
def read(cmd):
 p=subprocess.run(SSH+[cmd],capture_output=True,timeout=30);p.check_returncode();return p.stdout
report=[]
for dev in read('ls /sys/block | sed -n "/^sd[a-z]$/p"').decode().splitlines():
 bs=int(read(f'cat /sys/block/{dev}/queue/logical_block_size'))
 length=int(read(f'cat /sys/block/{dev}/size'))*512
 blocks=length//bs
 copies=[]
 for side,lba in [('primary',1),('backup',blocks-1)]:
  header=read(f'dd if=/dev/{dev} bs={bs} skip={lba} count=1 2>/dev/null')
  (DEST/f'{dev}-{side}-header.bin').write_bytes(header)
  if header[:8]!=b'EFI PART':
   copies.append(dict(side=side,signature_valid=False));continue
  size,crc=struct.unpack_from('<II',header,12)
  assert 92<=size<=bs
  check=bytearray(header[:size]);check[16:20]=bytes(4)
  hcrc=zlib.crc32(check)==crc
  current,alternate=struct.unpack_from('<QQ',header,24)
  table_lba,count,entry_size,tcrc=struct.unpack_from('<QIII',header,72)
  assert count<=4096 and 128<=entry_size<=1024 and count*entry_size<=1048576
  n=(count*entry_size+bs-1)//bs
  assert table_lba+n<=blocks
  table=read(f'dd if=/dev/{dev} bs={bs} skip={table_lba} count={n} 2>/dev/null')
  (DEST/f'{dev}-{side}-table.bin').write_bytes(table)
  valid=zlib.crc32(table[:count*entry_size])==tcrc
  entries=[]
  for i in range(count):
   e=table[i*entry_size:(i+1)*entry_size]
   if not any(e[:16]):continue
   name=e[56:128].decode('utf-16le').split('\0')[0]
   start,end,attr=struct.unpack_from('<QQQ',e,32)
   entries.append(dict(index=i,name=name,start=start,end=end,attributes=hex(attr),
     ab_byte=(attr>>48)&255,successful=bool(attr&(1<<54)),active=bool(attr&(1<<50)),
     unbootable=bool(attr&(1<<55)),retry_count=(attr>>51)&7))
  copies.append(dict(side=side,signature_valid=True,header_crc_valid=hcrc,table_crc_valid=valid,
   current_lba=current,alternate_lba=alternate,physical_header_lba=lba,table_lba=table_lba,
   table_count=count,entry_size=entry_size,entries=entries))
 report.append(dict(device=dev,block_size=bs,bytes=length,copies=copies))
(DEST/'gpt.json').write_text(json.dumps(report,indent=2)+'\n')
for disk in report:
 print(disk['device'],[(c['side'],c.get('header_crc_valid'),c.get('table_crc_valid'),c.get('current_lba')==c.get('physical_header_lba')) for c in disk['copies']])
 for c in disk['copies']:
  if c['side']=='primary':
   print([e for e in c.get('entries',[]) if e['name'] in ('boot_a','boot_b')])
print('Read-only GPT snapshots saved; no phone writes')
