"""Restore stock AVB metadata overwritten by a full-partition boot flash."""
import hashlib,json,struct
from pathlib import Path
root=Path(__file__).resolve().parents[1]
out=root/'out/boot-recovery-diagnosis-20261014'
stock=(root/'backup/boot_b.img').read_bytes()
working=(root/'out/display-port-20261013/round4/boot-xigua-r1.img').read_bytes()
magic,major,minor,size,offset,length,_=struct.unpack('>4sIIQQQ28s',stock[-64:])
assert magic==b'AVBf' and stock[offset:offset+4]==b'AVB0'
assert len(working)<offset and len(stock)==192*1024*1024
result=bytearray(stock)
result[:len(working)]=working
assert result[len(working):]==stock[len(working):]
path=out/'boot_b-working-restored-avb.img';path.write_bytes(result)
(out/'boot-repair-manifest.json').write_text(json.dumps({
 'boot_sha256':hashlib.sha256(result).hexdigest(),
 'original_avb_offset':offset,'original_avb_size':length,
 'original_tail_preserved':True,'working_boot_prefix_preserved':True,
 'note':'Stock signatures retained; changed payload hashes rely on existing unlocked behavior.',
 'phone_execution_confirmed':False},indent=2)+'\n')
print('PASS: working #14 boot prefix with original stock AVB metadata/footer restored')
