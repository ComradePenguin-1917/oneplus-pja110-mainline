"""Validate embedded archive/config, then package the existing boot format."""
import gzip
import hashlib
import json
import struct
from pathlib import Path
from bootimg import BootImage
from build_init_marker_test import lz4

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'out/debug-ncm-fixed-20261013'
BASE=ROOT/'out/user-init-usb-serial-diag-20261013'
image=(OUT/'Image-probe').read_bytes()
assert image[56:60]==b'ARM\x64'
symbols={p[2]:int(p[0],16) for line in (OUT/'System.map').read_text().splitlines() if len(p:=line.split())==3}
start=symbols['__initramfs_start']-symbols['_text']
size=struct.unpack_from('<Q',image,symbols['__initramfs_size']-symbols['_text'])[0]
assert gzip.decompress(image[start:start+size])==gzip.decompress((OUT/'initramfs.cpio.gz').read_bytes())
a=image.index(b'IKCFG_ST')+8
b=image.index(b'IKCFG_ED',a)
assert gzip.decompress(image[a:b])==(BASE/'kernel.config').read_bytes()==(OUT/'kernel.config').read_bytes()
boot=BootImage.parse(str(BASE/'boot-xigua-r1.img'))
boot.kernel=image
(OUT/'boot-xigua-r1.img').write_bytes(boot.pack(cmdline=boot.cmdline.decode()))
assert BootImage.parse(str(OUT/'boot-xigua-r1.img')).kernel==image
assert b'pja.qemu_validation' not in boot.cmdline
name='boot-xigua-r1.img'
external=bytearray((BASE/'init_boot_b-xigua-r1.img').read_bytes())
old_size=struct.unpack_from('<I',external,12)[0]
old_end=4096+((old_size+4095)//4096)*4096
ramdisk=lz4(['-z','-l','-12','-c'],gzip.decompress((OUT/'initramfs.cpio.gz').read_bytes()))
new_end=4096+((len(ramdisk)+4095)//4096)*4096
assert new_end<=len(external)
if new_end>old_end:
    assert not any(external[old_end:new_end]), 'would overwrite nonzero init_boot metadata'
end=max(old_end,new_end)
struct.pack_into('<I',external,12,len(ramdisk))
external[4096:end]=ramdisk.ljust(end-4096,b'\0')
assert lz4(['-d','-l','-c'],external[4096:4096+len(ramdisk)])==gzip.decompress((OUT/'initramfs.cpio.gz').read_bytes())
(OUT/'init_boot_b-xigua-r1.img').write_bytes(external)
manifest={'purpose':'Automatic NCM + key-only SSH debug boot',
          'phone_execution_confirmed':False,'kernel_config_unchanged':True,
          'ancillary_images_unchanged_from':str(BASE.relative_to(ROOT)),
          'contains_private_ssh_host_identity':True,
          'both_embedded_and_external_initramfs_updated':True,
          'files':{n:{'bytes':(OUT/n).stat().st_size,'sha256':hashlib.sha256((OUT/n).read_bytes()).hexdigest()} for n in (name,'init_boot_b-xigua-r1.img')}}
(OUT/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
print('PASS: embedded initramfs, unchanged kernel config and Android boot packing verified')
