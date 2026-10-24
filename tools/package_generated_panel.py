"""Package only the rebuilt kernel; preserve current external touch/SSH archive."""
import gzip
import hashlib
import json
import struct
import sys
from pathlib import Path
from bootimg import BootImage
ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'out/display-generator-20261013'
OUT=SOURCE
if '--avb-retest' in sys.argv:
    OUT=ROOT/'out/display-generator-avb-retest-20261014'
    OUT.mkdir(exist_ok=True)
    for name in ('Image','System.map','kernel.config','command-comparison.json',
                 'qemu-console.txt','adaptation-manifest.json','panel-adaptation.patch'):
        (OUT/name).write_bytes((SOURCE/name).read_bytes())
image=(OUT/'Image').read_bytes()
symbols={v[2]:int(v[0],16) for line in (OUT/'System.map').read_text().splitlines() if len(v:=line.split())==3}
assert all(name in symbols for name in ('aa536_prepare','aa536_probe'))  # on() may inline
assert json.loads((OUT/'command-comparison.json').read_text())['verified']
start=symbols['__initramfs_start']-symbols['_text']
length=struct.unpack_from('<Q',image,symbols['__initramfs_size']-symbols['_text'])[0]
assert gzip.decompress(image[start:start+length])==gzip.decompress((ROOT/'out/debug-ncm-fixed-20261013/initramfs.cpio.gz').read_bytes())
assert (OUT/'kernel.config').read_bytes()==(ROOT/'out/display-port-20261013/kernel.config').read_bytes()
assert b'AA536 generator-based 60Hz driver' in image
baseline=json.loads((ROOT/'out/boot-recovery-diagnosis-20261014/recovered-partition-hashes.json').read_text())
boot=BootImage.parse(str(ROOT/'out/display-port-20261013/round4/boot-xigua-r1.img'))
boot.kernel=image
packed=boot.pack(cmdline=boot.cmdline.decode())
assert len(packed)<=192*1024*1024
path=OUT/'boot_b-generated-panel.img'
stock=(ROOT/'backup/boot_b.img').read_bytes()
magic,_,_,_,avb_offset,avb_size,_=struct.unpack('>4sIIQQQ28s',stock[-64:])
assert magic==b'AVBf' and stock[avb_offset:avb_offset+4]==b'AVB0'
assert len(packed)<avb_offset
result=bytearray(stock)
result[:len(packed)]=packed
assert result[len(packed):]==stock[len(packed):]
path.write_bytes(result)
assert BootImage.parse(str(path)).kernel==image
(OUT/'deployment-manifest.json').write_text(json.dumps({'baseline_hashes':baseline,
    'boot_b_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
    'embedded_ssh_initramfs_preserved':True,'only_boot_b_to_flash':True,
    'original_avb_tail_preserved':True,'avb_offset':avb_offset,
    'phone_execution_confirmed':False},indent=2)+'\n')
print('PASS: new panel kernel packaged; embedded SSH unchanged; external touch/SSH archive retained')
